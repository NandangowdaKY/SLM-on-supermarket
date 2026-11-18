"""
Qwen3-style small language model, written from scratch in PyTorch.

Same architecture as notebook 5_slm_from_scratch_qwen.ipynb:
  token embedding -> N x [RMSNorm -> Grouped-Query Attention (QK-norm, RoPE) -> residual
                          RMSNorm -> SwiGLU feed-forward -> residual] -> RMSNorm -> LM head

Because it matches the Hugging Face `Qwen3ForCausalLM` layout one-to-one, a trained
checkpoint can be exported to safetensors (slm/export.py) and from there converted
to GGUF for Ollama.
"""
import torch
import torch.utils.checkpoint
import torch.nn as nn
import torch.nn.functional as F

# Qwen3 tokenizer: 151,643 BPE tokens + 26 special tokens (<|im_start|>, <|im_end|>, ...).
# `tokenizer.vocab_size` only counts the first 151,643, so the original notebook's
# embedding could not represent the chat special tokens.  Qwen pads the matrix to 151,936.
QWEN3_VOCAB_SIZE = 151_936

DEFAULT_CONFIG = dict(
    vocab_size=QWEN3_VOCAB_SIZE,
    d_model=768,
    n_heads=12,
    n_kv_groups=6,
    n_layers=12,
    d_ff=3072,
    max_seq_len=512,
    rope_theta=10_000.0,
)


def compute_rope_params(head_dim, theta_base=10_000, context_length=4096, dtype=torch.float32):
    assert head_dim % 2 == 0, "Embedding dimension must be even"
    inv_freq = 1.0 / (theta_base ** (torch.arange(0, head_dim, 2, dtype=dtype)[: (head_dim // 2)].float() / head_dim))
    positions = torch.arange(context_length, dtype=dtype)
    angles = positions[:, None] * inv_freq[None, :]
    angles = torch.cat([angles, angles], dim=1)
    return torch.cos(angles), torch.sin(angles)


def apply_rope(x, cos, sin):
    _, _, seq_len, head_dim = x.shape
    x1, x2 = x[..., : head_dim // 2], x[..., head_dim // 2:]
    cos = cos[:seq_len, :].unsqueeze(0).unsqueeze(0)
    sin = sin[:seq_len, :].unsqueeze(0).unsqueeze(0)
    rotated = torch.cat((-x2, x1), dim=-1)
    return ((x * cos) + (rotated * sin)).to(dtype=x.dtype)


class RMSNorm(nn.Module):
    def __init__(self, emb_dim, eps=1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(emb_dim))

    def forward(self, x):
        input_dtype = x.dtype
        x_f = x.float()
        x_norm = x_f * torch.rsqrt(x_f.pow(2).mean(dim=-1, keepdim=True) + self.eps)
        return (x_norm * self.weight.float()).to(input_dtype)


class GroupedQueryAttention(nn.Module):
    def __init__(self, d_in, num_heads, num_kv_groups, head_dim=None, dtype=None):
        super().__init__()
        assert num_heads % num_kv_groups == 0, "num_heads must be divisible by num_kv_groups"
        self.num_heads, self.num_kv_groups = num_heads, num_kv_groups
        self.group_size = num_heads // num_kv_groups
        self.head_dim = head_dim or d_in // num_heads
        self.d_out = num_heads * self.head_dim
        self.W_query = nn.Linear(d_in, self.d_out, bias=False, dtype=dtype)
        self.W_key = nn.Linear(d_in, num_kv_groups * self.head_dim, bias=False, dtype=dtype)
        self.W_value = nn.Linear(d_in, num_kv_groups * self.head_dim, bias=False, dtype=dtype)
        self.out_proj = nn.Linear(self.d_out, d_in, bias=False, dtype=dtype)
        self.q_norm = RMSNorm(self.head_dim, eps=1e-6)
        self.k_norm = RMSNorm(self.head_dim, eps=1e-6)

    def forward(self, x, mask, cos, sin):
        b, t, _ = x.shape
        q = self.W_query(x).view(b, t, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.W_key(x).view(b, t, self.num_kv_groups, self.head_dim).transpose(1, 2)
        v = self.W_value(x).view(b, t, self.num_kv_groups, self.head_dim).transpose(1, 2)
        q, k = self.q_norm(q), self.k_norm(k)
        q, k = apply_rope(q, cos, sin), apply_rope(k, cos, sin)
        k = k.repeat_interleave(self.group_size, dim=1)
        v = v.repeat_interleave(self.group_size, dim=1)
        # fused attention kernel (FlashAttention / memory-efficient on GPU); same maths as
        # softmax(QK^T / sqrt(d) + causal mask) V in the original notebook
        ctx = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        return self.out_proj(ctx.transpose(1, 2).reshape(b, t, self.d_out))


class SwiGLUFeedForward(nn.Module):
    def __init__(self, d_model, d_ff, dtype=None):
        super().__init__()
        self.gate_proj = nn.Linear(d_model, d_ff, bias=False, dtype=dtype)
        self.up_proj = nn.Linear(d_model, d_ff, bias=False, dtype=dtype)
        self.down_proj = nn.Linear(d_ff, d_model, bias=False, dtype=dtype)

    def forward(self, x):
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class TransformerBlock(nn.Module):
    def __init__(self, d_model, n_heads, n_kv_groups, d_ff, dtype=None):
        super().__init__()
        self.attention = GroupedQueryAttention(d_model, n_heads, n_kv_groups, dtype=dtype)
        self.feed_forward = SwiGLUFeedForward(d_model, d_ff, dtype=dtype)
        self.norm1 = RMSNorm(d_model, eps=1e-6)
        self.norm2 = RMSNorm(d_model, eps=1e-6)

    def forward(self, x, mask, cos, sin):
        x = x + self.attention(self.norm1(x), mask, cos, sin)
        return x + self.feed_forward(self.norm2(x))


class Qwen3Model(nn.Module):
    def __init__(self, vocab_size, d_model, n_heads, n_kv_groups, n_layers, d_ff, max_seq_len,
                 rope_theta=10_000.0, dtype=None):
        super().__init__()
        self.config = dict(vocab_size=vocab_size, d_model=d_model, n_heads=n_heads, n_kv_groups=n_kv_groups,
                           n_layers=n_layers, d_ff=d_ff, max_seq_len=max_seq_len, rope_theta=rope_theta)
        self.tok_emb = nn.Embedding(vocab_size, d_model, dtype=dtype)
        self.blocks = nn.ModuleList([TransformerBlock(d_model, n_heads, n_kv_groups, d_ff, dtype=dtype)
                                     for _ in range(n_layers)])
        self.final_norm = RMSNorm(d_model, eps=1e-6)
        self.out_head = nn.Linear(d_model, vocab_size, bias=False, dtype=dtype)
        cos, sin = compute_rope_params(d_model // n_heads, theta_base=rope_theta, context_length=max_seq_len)
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)
        self.d_model, self.max_seq_len = d_model, max_seq_len
        self.gradient_checkpointing = False   # recompute block activations in backward (low-VRAM GPUs)

    def forward(self, input_ids, targets=None, loss_mask=None):
        x = self.tok_emb(input_ids) * (self.d_model ** 0.5)
        for block in self.blocks:
            if self.gradient_checkpointing and self.training:
                x = torch.utils.checkpoint.checkpoint(block, x, None, self.cos, self.sin, use_reentrant=False)
            else:
                x = block(x, None, self.cos, self.sin)
        logits = self.out_head(self.final_norm(x))
        loss = None
        if targets is not None:
            if loss_mask is None:
                loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)).float(), targets.reshape(-1))
            else:   # SFT: only learn the assistant's tokens
                per_tok = F.cross_entropy(logits.reshape(-1, logits.size(-1)).float(), targets.reshape(-1),
                                          reduction="none")
                m = loss_mask.reshape(-1).float()
                loss = (per_tok * m).sum() / m.sum().clamp(min=1)
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, max_new_tokens, temperature=1.0, top_k=None, top_p=None,
                 repetition_penalty=1.0, eos_token_ids=()):
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.max_seq_len:]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :].float()
            if repetition_penalty != 1.0:
                prev = torch.gather(logits, 1, idx)
                logits.scatter_(1, idx, torch.where(prev > 0, prev / repetition_penalty, prev * repetition_penalty))
            if temperature <= 0:
                idx_next = logits.argmax(dim=-1, keepdim=True)
            else:
                logits = logits / temperature
                if top_k is not None:
                    v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                    logits[logits < v[:, [-1]]] = float("-inf")
                if top_p is not None:
                    sorted_logits, sorted_idx = torch.sort(logits, descending=True)
                    cum = torch.softmax(sorted_logits, dim=-1).cumsum(dim=-1)
                    remove = cum - torch.softmax(sorted_logits, dim=-1) > top_p
                    sorted_logits[remove] = float("-inf")
                    logits = torch.full_like(logits, float("-inf")).scatter(1, sorted_idx, sorted_logits)
                idx_next = torch.multinomial(torch.softmax(logits, dim=-1), num_samples=1)
            idx = torch.cat((idx, idx_next), dim=1)
            if eos_token_ids and idx_next.item() in eos_token_ids:
                break
        return idx


def resize_vocab(state_dict, new_vocab_size):
    """Grow tok_emb / out_head of an old checkpoint (vocab 151,643) to 151,936 rows.
    New rows (chat special tokens) are initialised to the mean embedding so SFT can learn them."""
    sd = dict(state_dict)
    for key in ("tok_emb.weight", "out_head.weight"):
        w = sd[key]
        if w.shape[0] < new_vocab_size:
            extra = w.float().mean(0, keepdim=True).repeat(new_vocab_size - w.shape[0], 1).to(w.dtype)
            sd[key] = torch.cat([w, extra], dim=0)
    return sd


def count_parameters(model):
    return sum(p.numel() for p in model.parameters())
