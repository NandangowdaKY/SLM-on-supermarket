"""
Build the training datasets for the SuperMart SLM.

Inputs (project root)
  combined_supermarket_data.csv   2.6M transaction lines (dunnhumby "The Complete Journey"
                                  schema: transactions + product hierarchy + household
                                  demographics + causal display/mailer flags)
  design_thinking_merged.jsonl    11 cleaned research documents (run clean_jsonl.py first)

Outputs (data/)
  stats/dataset_stats.json        every aggregate used below (statistical analysis of the CSV)
  transactions_corpus_{train,val}.txt  one line of text per basket (276k baskets)
                                  (stage-1 pre-training from scratch on our own data)
  pretrain_corpus.jsonl           {"text","source"}  - research docs + data-insight paragraphs
                                  (stage-2 domain-adaptive pre-training)
  sft_train.jsonl / sft_val.jsonl {"messages":[system,user,assistant],"source","group"}
                                  (stage-3 supervised chat fine-tuning, ChatML via the
                                  Qwen3 chat template)

Every answer is computed from the data, so the model is trained on facts that are
true for this dataset.  Paraphrases of the same fact share a `group` and always land
in the same split (no train/val leakage).

Usage:  python scripts/build_dataset.py [--csv path] [--val-frac 0.1]
"""
import argparse
import hashlib
import json
import os
import re

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

SYSTEM_PROMPT = (
    "You are SuperMart SLM, a small language model trained from scratch to answer questions "
    "about supermarket retail analytics: sales, products, departments, discounts, baskets, "
    "customer demographics, gross margin, pricing, payment methods and tax. "
    "Answer concisely and use the numbers from the SuperMart transaction dataset when relevant."
)

NON_UNIT_DEPTS = {"KIOSK-GAS", "MISC SALES TRAN"}
MARITAL = {"A": "married", "B": "single", "U": "unknown marital status"}

COLS = ["household_key", "BASKET_ID", "DAY", "PRODUCT_ID", "QUANTITY", "SALES_VALUE", "STORE_ID",
        "RETAIL_DISC", "TRANS_TIME", "WEEK_NO", "COUPON_DISC", "COUPON_MATCH_DISC", "DEPARTMENT",
        "BRAND", "COMMODITY_DESC", "SUB_COMMODITY_DESC", "CURR_SIZE_OF_PRODUCT", "AGE_DESC", "MARITAL_STATUS_CODE", "INCOME_DESC",
        "HOMEOWNER_DESC", "HH_COMP_DESC", "HOUSEHOLD_SIZE_DESC", "KID_CATEGORY_DESC",
        "display", "mailer"]


def money(x):
    return f"${x:,.2f}"


def pct(x):
    return f"{x * 100:.1f}%"


def nice(s):
    """'CONVENIENT BRKFST/WHLSM SNACKS' -> 'Convenient Brkfst/Whlsm Snacks'"""
    return " ".join(w.capitalize() if w.isalpha() else w.title() for w in str(s).split())


class QA:
    def __init__(self):
        self.items = []

    def add(self, group, questions, answer, source):
        for q in questions:
            self.items.append({"group": group, "q": q.strip(), "a": answer.strip(), "source": source})


# --------------------------------------------------------------------------------------
# CSV statistics -> Q&A
# --------------------------------------------------------------------------------------
def load_csv(path):
    print(f"reading {path} ...")
    df = pd.read_csv(path, usecols=COLS, low_memory=False,
                     dtype={"DEPARTMENT": "category", "BRAND": "category", "COMMODITY_DESC": "category",
                            "SUB_COMMODITY_DESC": "category", "CURR_SIZE_OF_PRODUCT": "category",
                            "AGE_DESC": "category", "MARITAL_STATUS_CODE": "category",
                            "INCOME_DESC": "category", "HOMEOWNER_DESC": "category",
                            "HH_COMP_DESC": "category", "HOUSEHOLD_SIZE_DESC": "category",
                            "KID_CATEGORY_DESC": "category", "display": "string", "mailer": "string"})
    print(f"  {len(df):,} rows x {df.shape[1]} cols")
    for c in ["DEPARTMENT", "COMMODITY_DESC", "BRAND"]:
        df[c] = df[c].astype("string").str.strip().replace("", pd.NA).astype("category")
    return df


def build_csv_qa(df, qa, stats, corpus):
    S = "supermarket_csv"
    total_sales = float(df.SALES_VALUE.sum())
    n_baskets = df.BASKET_ID.nunique()
    n_hh = df.household_key.nunique()
    n_products = df.PRODUCT_ID.nunique()
    n_stores = df.STORE_ID.nunique()
    weeks = (int(df.WEEK_NO.min()), int(df.WEEK_NO.max()))
    days = (int(df.DAY.min()), int(df.DAY.max()))
    df["is_fuel_misc"] = df.DEPARTMENT.isin(NON_UNIT_DEPTS)   # QUANTITY there = gallons / misc counters
    units = int(df.loc[~df.is_fuel_misc, "QUANTITY"].sum())
    ov = dict(rows=len(df), total_sales=total_sales, baskets=n_baskets, households=n_hh,
              products=n_products, stores=n_stores, weeks=weeks, days=days, units=units)
    stats["overview"] = ov

    ans = (f"The SuperMart dataset contains {len(df):,} transaction lines from {n_baskets:,} shopping baskets "
           f"made by {n_hh:,} households across {n_stores:,} stores, covering {n_products:,} distinct products "
           f"over {days[1]} days (weeks {weeks[0]}-{weeks[1]}). Total sales value is {money(total_sales)}.")
    qa.add("overview", ["Give me an overview of the SuperMart dataset.",
                        "What does the supermarket transaction dataset contain?",
                        "Describe the dataset you were trained on."], ans, S)
    corpus.append(ans)
    qa.add("total_sales", ["What is the total sales value in the dataset?",
                           "How much revenue did SuperMart make in total?"],
           f"The total sales value across all {len(df):,} transaction lines is {money(total_sales)}.", S)
    qa.add("n_households", ["How many households are in the dataset?", "How many customers does the data cover?"],
           f"The data covers {n_hh:,} households (customers), who made {n_baskets:,} shopping trips (baskets).", S)
    qa.add("n_stores", ["How many stores are in the dataset?"],
           f"Transactions come from {n_stores:,} different stores.", S)
    qa.add("n_products", ["How many different products were sold?"],
           f"{n_products:,} distinct products were sold, totalling {units:,} units "
           f"(excluding fuel and miscellaneous kiosk transactions).", S)

    # ---------------- baskets ----------------
    b = df.groupby("BASKET_ID").agg(value=("SALES_VALUE", "sum"), items=("QUANTITY", "size"))
    bs = dict(mean=float(b.value.mean()), median=float(b.value.median()), p90=float(b.value.quantile(.9)),
              items_mean=float(b["items"].mean()), items_median=float(b["items"].median()))
    stats["basket"] = bs
    ans = (f"The average basket value is {money(bs['mean'])} (median {money(bs['median'])}; 90th percentile "
           f"{money(bs['p90'])}). An average basket contains {bs['items_mean']:.1f} line items "
           f"(median {bs['items_median']:.0f}).")
    qa.add("basket", ["What is the average basket size?", "What is the average transaction value?",
                      "How much does a typical customer spend per shopping trip?"], ans, S)
    corpus.append(ans)

    hh = df.groupby("household_key").agg(sales=("SALES_VALUE", "sum"), trips=("BASKET_ID", "nunique"))
    hs = dict(mean_spend=float(hh.sales.mean()), median_spend=float(hh.sales.median()),
              mean_trips=float(hh.trips.mean()))
    stats["household"] = hs
    ans = (f"Over the whole period a household spends on average {money(hs['mean_spend'])} "
           f"(median {money(hs['median_spend'])}) across {hs['mean_trips']:.0f} shopping trips.")
    qa.add("hh_spend", ["How much does an average household spend?",
                        "How many shopping trips does a household make on average?"], ans, S)
    corpus.append(ans)

    # ---------------- departments ----------------
    dep = (df.groupby("DEPARTMENT", observed=True)
             .agg(sales=("SALES_VALUE", "sum"), units=("QUANTITY", "sum"), lines=("SALES_VALUE", "size"))
             .sort_values("sales", ascending=False))
    dep = dep[dep.sales > 0]
    dep["share"] = dep.sales / total_sales
    stats["departments"] = dep.reset_index().to_dict("records")
    top = dep.head(5)
    ans = "The top departments by sales are: " + "; ".join(
        f"{i + 1}. {nice(d)} ({money(r.sales)}, {pct(r.share)} of sales)" for i, (d, r) in enumerate(top.iterrows())) + "."
    qa.add("top_departments", ["Which departments generate the most sales?",
                               "What are the top 5 departments by revenue?",
                               "Which department has the highest sales?"], ans, S)
    corpus.append(ans)
    qa.add("n_departments", ["How many departments are there?"],
           f"Products are organised into {len(dep)} departments with sales; the largest is {nice(dep.index[0])} "
           f"with {pct(dep.share.iloc[0])} of total sales.", S)
    for d, r in dep.iterrows():
        if r.lines < 500:
            continue
        sold = "" if d in NON_UNIT_DEPTS else f"sold {int(r.units):,} units for "
        ans = (f"The {nice(d)} department {sold}{'generated ' if not sold else ''}{money(r.sales)} in sales, "
               f"which is {pct(r.share)} of total sales (rank {dep.index.get_loc(d) + 1} of {len(dep)}).")
        qa.add(f"dep:{d}", [f"What are the total sales of the {nice(d)} department?",
                            f"How is the {nice(d)} department performing?"], ans, S)
        corpus.append(ans)

    # ---------------- commodities ----------------
    df["unit_price"] = np.where(df.QUANTITY > 0, df.SALES_VALUE / df.QUANTITY.clip(lower=1), np.nan)
    com = (df[~df.is_fuel_misc].groupby("COMMODITY_DESC", observed=True)
             .agg(sales=("SALES_VALUE", "sum"), units=("QUANTITY", "sum"), lines=("SALES_VALUE", "size"),
                  med_price=("unit_price", "median"),
                  dept=("DEPARTMENT", lambda s: s.mode().iloc[0] if len(s.mode()) else "UNKNOWN"),
                  private=("BRAND", lambda s: (s == "Private").mean()))
             .sort_values("sales", ascending=False))
    com["share"] = com.sales / total_sales
    stats["top_commodities"] = com.head(50).reset_index().to_dict("records")
    ans = "Excluding fuel, the best-selling product categories (commodities) are: " + "; ".join(
        f"{i + 1}. {nice(c)} ({money(r.sales)})" for i, (c, r) in enumerate(com.head(10).iterrows())) + "."
    qa.add("top_commodities", ["What are the best-selling product categories?",
                               "Which commodities sell the most?",
                               "List the top 10 commodities by sales."], ans, S)
    corpus.append(ans)
    for c, r in com.head(150).iterrows():
        if r.lines < 300:
            continue
        price = f" The median price per unit is {money(r.med_price)}." if pd.notna(r.med_price) else ""
        ans = (f"{nice(c)} belongs to the {nice(r.dept)} department and generated {money(r.sales)} in sales "
               f"({pct(r.share)} of the total, rank {com.index.get_loc(c) + 1}) from {int(r.lines):,} purchases."
               f"{price} Private-label products account for {pct(r.private)} of its line items.")
        qa.add(f"com:{c}", [f"Tell me about sales of {nice(c).lower()}.",
                            f"How much {nice(c).lower()} was sold?"], ans, S)
        corpus.append(ans)
    for d in dep.head(8).index:
        sub = com[com.dept == d].head(5)
        if len(sub) < 3:
            continue
        ans = f"In the {nice(d)} department the top commodities are " + ", ".join(
            f"{nice(c)} ({money(r.sales)})" for c, r in sub.iterrows()) + "."
        qa.add(f"depcom:{d}", [f"What are the top products in the {nice(d)} department?",
                               f"Which commodities lead {nice(d).lower()} sales?"], ans, S)
        corpus.append(ans)

    # ---------------- brand type ----------------
    br = df.groupby("BRAND", observed=True).SALES_VALUE.sum()
    br_share = (br / br.sum()).to_dict()
    stats["brand_share"] = br_share
    if "Private" in br_share and "National" in br_share:
        ans = (f"National brands account for {pct(br_share['National'])} of sales ({money(br['National'])}) and "
               f"private-label (store) brands for {pct(br_share['Private'])} ({money(br['Private'])}).")
        qa.add("brand", ["What share of sales comes from private label brands?",
                         "Compare national brands and private label sales.",
                         "Do customers buy more national or store brands?"], ans, S)
        corpus.append(ans)

    # ---------------- discounts / coupons ----------------
    disc = dict(retail_disc=float(-df.RETAIL_DISC.sum()), coupon_disc=float(-df.COUPON_DISC.sum()),
                coupon_match=float(-df.COUPON_MATCH_DISC.sum()),
                share_lines_retail=float((df.RETAIL_DISC < 0).mean()),
                share_lines_coupon=float((df.COUPON_DISC < 0).mean()),
                share_baskets_coupon=float(df.loc[df.COUPON_DISC < 0, "BASKET_ID"].nunique() / n_baskets))
    stats["discounts"] = disc
    ans = (f"Loyalty-card retail discounts total {money(disc['retail_disc'])} and are applied to "
           f"{pct(disc['share_lines_retail'])} of line items. Manufacturer coupons saved customers "
           f"{money(disc['coupon_disc'])} (plus {money(disc['coupon_match'])} in store coupon matching); "
           f"coupons appear on only {pct(disc['share_lines_coupon'])} of items and in "
           f"{pct(disc['share_baskets_coupon'])} of baskets.")
    qa.add("discounts", ["How much discount was given to customers?", "How often are coupons used?",
                         "Analyse discounts and coupon usage."], ans, S)
    corpus.append(ans)
    dd = df[df.RETAIL_DISC < 0].groupby("DEPARTMENT", observed=True).RETAIL_DISC.sum().sort_values().head(3)
    ans = "The departments receiving the most retail discount are " + ", ".join(
        f"{nice(d)} ({money(-v)})" for d, v in dd.items()) + "."
    qa.add("disc_dep", ["Which departments get the most discounts?"], ans, S)

    # ---------------- time ----------------
    df["hour"] = (df.TRANS_TIME // 100).clip(0, 23)
    hr = df.groupby("hour").SALES_VALUE.sum()
    hr_share = hr / hr.sum()
    stats["sales_by_hour"] = {int(k): float(v) for k, v in hr.items()}
    peak = int(hr.idxmax())
    parts = {"morning (6-12)": hr_share.loc[6:11].sum(), "afternoon (12-17)": hr_share.loc[12:16].sum(),
             "evening (17-22)": hr_share.loc[17:21].sum()}
    ans = (f"Sales peak at {peak}:00-{peak + 1}:00 ({pct(hr_share[peak])} of daily sales). "
           + "The " + ", ".join(f"{k} brings {pct(v)}" for k, v in parts.items()) + " of sales.")
    qa.add("hour", ["What time of day do customers shop the most?", "What is the peak shopping hour?",
                    "How are sales distributed across the day?"], ans, S)
    corpus.append(ans)

    wk = df.groupby("WEEK_NO").SALES_VALUE.sum()
    full = wk.iloc[4:-1] if len(wk) > 10 else wk      # first weeks & last week are partial
    stats["sales_by_week"] = {int(k): float(v) for k, v in wk.items()}
    half = len(full) // 2
    growth = full.iloc[half:].mean() / full.iloc[:half].mean() - 1
    ans = (f"Weekly sales average {money(full.mean())} (std {money(full.std())}). The best week was week "
           f"{int(full.idxmax())} ({money(full.max())}) and the weakest full week was week {int(full.idxmin())} "
           f"({money(full.min())}). Average weekly sales in the second half of the period were "
           f"{pct(abs(growth))} {'higher' if growth >= 0 else 'lower'} than in the first half.")
    qa.add("weekly", ["What is the weekly sales trend?", "Which week had the highest sales?",
                      "Are sales growing over time?"], ans, S)
    corpus.append(ans)

    # ---------------- stores ----------------
    st = df.groupby("STORE_ID").SALES_VALUE.sum().sort_values(ascending=False)
    stats["top_stores"] = {int(k): float(v) for k, v in st.head(10).items()}
    ans = (f"The top 5 stores by sales are " + ", ".join(f"store {k} ({money(v)})" for k, v in st.head(5).items())
           + f". The top 10 stores together generate {pct(st.head(10).sum() / st.sum())} of all sales.")
    qa.add("stores", ["Which stores have the highest sales?", "What are the top performing stores?"], ans, S)
    corpus.append(ans)

    # ---------------- promotions (display / mailer) ----------------
    for col, label in [("display", "in-store display"), ("mailer", "mailer (flyer) advertising")]:
        filled = df[col].notna() & (df[col].str.strip() != "")
        if filled.mean() < 0.01:
            continue
        promo = filled & (df[col].str.strip() != "0")
        a, b_ = df.loc[promo, "QUANTITY"].mean(), df.loc[filled & ~promo, "QUANTITY"].mean()
        stats[f"{col}_effect"] = dict(coverage=float(filled.mean()), promo_share=float(promo.mean()),
                                      qty_promo=float(a), qty_nopromo=float(b_))
        if pd.notna(a) and pd.notna(b_) and b_ > 0:
            ans = (f"Promotion data is recorded for {pct(filled.mean())} of line items; among those, "
                   f"{pct(promo.sum() / filled.sum())} were on {label}. Promoted items sell {a:.2f} units per "
                   f"purchase on average versus {b_:.2f} without promotion ({pct(abs(a / b_ - 1))} "
                   f"{'more' if a >= b_ else 'less'}).")
            qa.add(f"promo:{col}", [f"What is the effect of {label} on sales?",
                                    f"Do {label.split(' (')[0]} promotions increase sales?"], ans, S)
            corpus.append(ans)

    # ---------------- demographics ----------------
    demo = df[df.AGE_DESC.notna()]
    stats["demographics_coverage"] = dict(households=int(demo.household_key.nunique()),
                                          share_sales=float(demo.SALES_VALUE.sum() / total_sales))
    qa.add("demo_cov", ["How many households have demographic information?"],
           f"Demographic data is available for {demo.household_key.nunique():,} of {n_hh:,} households, "
           f"who account for {pct(demo.SALES_VALUE.sum() / total_sales)} of sales.", S)
    dims = [("AGE_DESC", "age group", "age group"), ("INCOME_DESC", "income band", "income level"),
            ("MARITAL_STATUS_CODE", "marital status", "marital status"),
            ("HOMEOWNER_DESC", "homeowner status", "home ownership"),
            ("HH_COMP_DESC", "household composition", "household type"),
            ("HOUSEHOLD_SIZE_DESC", "household size", "household size"),
            ("KID_CATEGORY_DESC", "number of kids", "number of children")]
    stats["demographics"] = {}
    for col, label, alt in dims:
        g = demo.groupby(col, observed=True).agg(sales=("SALES_VALUE", "sum"), hh=("household_key", "nunique"),
                                                 baskets=("BASKET_ID", "nunique"))
        g["per_hh"] = g.sales / g.hh
        g["basket_value"] = g.sales / g.baskets
        g = g.sort_values("per_hh", ascending=False)
        name = (lambda k: MARITAL.get(str(k), str(k))) if col == "MARITAL_STATUS_CODE" else str
        stats["demographics"][col] = {name(k): v for k, v in g.to_dict("index").items()}
        ans = (f"By {label}, average spend per household is: " + "; ".join(
            f"{name(k)}: {money(r.per_hh)} ({int(r.hh)} households, avg basket {money(r.basket_value)})"
            for k, r in g.iterrows()) + f". The highest-spending segment is '{name(g.index[0])}'.")
        qa.add(f"demo:{col}", [f"How does spending vary by {alt}?", f"Which {label} spends the most?",
                               f"Analyse customer spending by {label}."], ans, S)
        corpus.append(ans)
    for age in demo.AGE_DESC.cat.categories:
        sub = demo[demo.AGE_DESC == age].groupby("DEPARTMENT", observed=True).SALES_VALUE.sum()
        sub = sub.sort_values(ascending=False).head(3) / sub.sum()
        ans = f"Customers aged {age} spend most on " + ", ".join(f"{nice(d)} ({pct(v)})" for d, v in sub.items()) + "."
        qa.add(f"age_dep:{age}", [f"What do customers aged {age} buy the most?"], ans, S)
        corpus.append(ans)


# --------------------------------------------------------------------------------------
# Transactions -> natural-language basket descriptions (stage-A pre-training corpus)
# --------------------------------------------------------------------------------------
def build_transaction_corpus(df, path, val_frac=0.05):
    """One line of text per shopping basket, e.g.
    'Store 364, week 1, day 1 at 16:31. Household 2375 (age 45-54, married, income 50-74K, homeowner,
     2 adults no kids, 2 people). Bought: Potatoes Russet (Bulk&Bag) (Produce, private label, 5 LB) x1 for $1.39,
     saved $0.60; ... Basket total $12.34 for 9 items.'
    The last `val_frac` of baskets (by time) are written to the validation file."""
    def catmap(col):
        return df[col].astype("category").cat.rename_categories(lambda c: nice(c)).astype("string").fillna("")

    sub = catmap("SUB_COMMODITY_DESC")
    sub = sub.where(sub != "", catmap("COMMODITY_DESC"))
    dept = catmap("DEPARTMENT")
    brand = df.BRAND.astype("string").map({"Private": "private label", "National": "national brand"}).fillna("")
    size = df.CURR_SIZE_OF_PRODUCT.astype("string").str.strip().fillna("")
    meta = dept + (", " + brand).where(brand != "", "") + (", " + size).where(size != "", "")
    disc = (-(df.RETAIL_DISC + df.COUPON_DISC)).round(2)
    item = (sub + " (" + meta + ") x" + df.QUANTITY.astype(str) + " for $" + df.SALES_VALUE.map("{:.2f}".format)
            + (", saved $" + disc.map("{:.2f}".format)).where(disc > 0, ""))
    df = df.assign(_item=item)

    hh = df.drop_duplicates("household_key").set_index("household_key")
    demo = {}
    for k, r in hh.iterrows():
        if pd.isna(r.AGE_DESC):
            demo[k] = f"Household {k}"
            continue
        kids = str(r.KID_CATEGORY_DESC)
        kids = "" if kids in ("None/Unknown", "nan") else f", {kids} kid(s)"
        home = str(r.HOMEOWNER_DESC).lower()
        home = "unknown home ownership" if home in ("unknown", "nan") else home
        demo[k] = (f"Household {k} (age {r.AGE_DESC}, {MARITAL.get(str(r.MARITAL_STATUS_CODE), 'unknown marital status')}, "
                   f"income {r.INCOME_DESC}, {home}, {r.HH_COMP_DESC}, "
                   f"{r.HOUSEHOLD_SIZE_DESC} {'person' if str(r.HOUSEHOLD_SIZE_DESC) == '1' else 'people'}{kids})")

    df = df.sort_values(["DAY", "TRANS_TIME", "BASKET_ID"], kind="stable")
    g = df.groupby("BASKET_ID", sort=False)
    head = g[["STORE_ID", "WEEK_NO", "DAY", "TRANS_TIME", "household_key"]].first()
    items = g["_item"].agg("; ".join)
    total = g["SALES_VALUE"].sum()
    n = g.size()
    lines = [f"Store {r.STORE_ID}, week {r.WEEK_NO}, day {r.DAY} at {r.TRANS_TIME // 100:02d}:{r.TRANS_TIME % 100:02d}. "
             f"{demo[r.household_key]}. Bought: {it}. Basket total ${t:.2f} for {c} items."
             for r, it, t, c in zip(head.itertuples(), items.values, total.values, n.values)]
    cut = int(len(lines) * (1 - val_frac))
    base = os.path.splitext(path)[0]
    for suffix, part in [("_train.txt", lines[:cut]), ("_val.txt", lines[cut:])]:
        with open(base + suffix, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(part) + "\n")
    chars = sum(map(len, lines))
    print(f"transaction corpus: {len(lines):,} baskets, {chars:,} chars (~{chars / 2.25 / 1e6:.0f}M tokens) "
          f"-> {base}_train.txt / _val.txt")
    print("  example:", lines[0][:400])


# --------------------------------------------------------------------------------------
# Research documents -> summary Q&A + corpus
# --------------------------------------------------------------------------------------
def build_doc_qa(docs, qa, corpus_docs):
    # A topic name may belong to two docs (a duplicate file alias + a "(2)" file).
    # The doc whose own file name gives the topic wins, so each question has one answer.
    primary = {d["topics"][0] for d in docs}
    for d in docs:
        d["topics"] = [t for i, t in enumerate(d["topics"]) if i == 0 or t not in primary]
    for d in docs:
        text = d["content"]
        corpus_docs.append({"text": text, "source": f"research:{d['file_name']}"})
        m = re.search(r"abstract[\s:.\-]*\n?(.{200,2500}?)(?:\n\s*\n|keywords|key words|index terms|1\.?\s*introduction)",
                      text, re.I | re.S)
        if not m:
            continue
        abstract = " ".join(m.group(1).split())
        words = abstract.split()
        if len(words) < 40:
            continue
        if sum(len(w) > 20 for w in words) / len(words) > 0.02:
            continue        # PDF lost the spaces ("includesvariablessuchasage") - not usable as an answer
        abstract = " ".join(words[:160]) + ("..." if len(words) > 160 else "")
        for topic in d["topics"]:
            qa.add(f"doc:{d['id']}", [f"Summarise the research on {topic.lower()}.",
                                      f"What does the literature say about {topic.lower()}?"], abstract,
                   f"research:{d['file_name']}")


# Hand-written domain glossary (concepts covered by the research documents)
GLOSSARY = [
    ("gross margin", "Gross margin is the difference between the selling price and the cost price of goods, usually expressed as a percentage of the selling price: Gross margin % = (Sales - Cost of goods sold) / Sales x 100. A product that sells for $10 and costs $6 has a gross margin of 40%."),
    ("markup", "Markup is the amount added to the cost price to get the selling price, expressed as a percentage of cost: Markup % = (Price - Cost) / Cost x 100. A $6 item sold at $10 has a 66.7% markup but a 40% gross margin, so markup is always larger than margin."),
    ("gross profit", "Gross profit is revenue minus the cost of goods sold, in currency rather than percent. It is the money left to cover operating expenses such as wages, rent and marketing."),
    ("net profit", "Net profit is what remains after all expenses - cost of goods, operating costs, interest and tax - are deducted from revenue. It is the most complete measure of business profitability."),
    ("unit price", "Unit price is the price per single unit of a product (for example per item, per kg or per litre). It lets shoppers and analysts compare value across pack sizes: unit price = total price / quantity."),
    ("average basket value", "Average basket value (average transaction value) is total sales divided by the number of shopping baskets. Retailers raise it through cross-selling, bundles and promotions."),
    ("basket analysis", "Market basket analysis finds products that are frequently bought together, using association rules measured by support, confidence and lift. It is used for store layout, cross-selling and promotions."),
    ("RFM analysis", "RFM analysis segments customers by Recency (how recently they bought), Frequency (how often they buy) and Monetary value (how much they spend). Each customer gets a score per dimension and segments such as Champions, Loyal customers or At-risk customers are derived."),
    ("customer segmentation", "Customer segmentation groups customers with similar characteristics or behaviour - for example by demographics, RFM scores or purchase patterns - often using clustering algorithms such as K-means, so marketing can be targeted to each group."),
    ("K-means clustering", "K-means is an unsupervised algorithm that partitions customers into k clusters by repeatedly assigning each point to the nearest cluster centre and recomputing the centres. The elbow method or silhouette score is used to choose k."),
    ("customer lifetime value", "Customer lifetime value (CLV) estimates the total revenue or profit a customer will generate over the relationship: roughly average purchase value x purchase frequency x customer lifespan."),
    ("private label", "Private-label (store-brand) products are sold under the retailer's own brand. They are usually cheaper for customers and carry higher gross margins for the retailer than national brands."),
    ("national brand", "National brands are products made and marketed by manufacturers and sold across many retailers, such as well-known packaged goods brands."),
    ("loyalty discount", "A loyalty (retail) discount is a price reduction given to customers who use the store's loyalty card. It encourages repeat visits and gives the retailer customer-level purchase data."),
    ("coupon", "A coupon is a voucher that reduces the price of a product. Manufacturer coupons are funded by the brand; store coupon matching means the retailer adds extra value on top of a manufacturer coupon."),
    ("price elasticity", "Price elasticity of demand measures how much the quantity sold changes when the price changes: elasticity = % change in quantity / % change in price. Elastic products (|e| > 1) are price-sensitive."),
    ("demand forecasting", "Demand forecasting predicts future sales quantities using historical sales, seasonality, price, promotions and external factors, with methods ranging from moving averages to regression trees and machine learning."),
    ("price optimization", "Price optimisation chooses prices that maximise revenue or profit given forecast demand. Research with online retailer Rue La La combined a regression-tree demand model with an integer program to set prices and increased revenue."),
    ("dynamic pricing", "Dynamic pricing changes prices over time in response to demand, inventory, competition or time of day, and is common in e-commerce and fuel retail."),
    ("sales revenue", "Sales revenue is quantity sold multiplied by the selling price, summed over all transactions, before deducting costs."),
    ("total transaction value", "Total transaction value is the sum of all line items in a purchase after discounts: sum(quantity x unit price) - discounts + tax where applicable."),
    ("GST", "Goods and Services Tax (GST) is a value-added tax on the supply of goods and services. In India it is split into CGST and SGST for sales within a state and IGST for sales between states; businesses claim input tax credit for GST paid on purchases."),
    ("tax calculation", "Sales tax is usually calculated as taxable value x tax rate. For example a $100 item with 18% GST carries $18 tax, so the invoice total is $118. Tax engines apply rules for applicability, rates, exemptions and posting to accounts."),
    ("input tax credit", "Input tax credit lets a registered business deduct the tax it paid on purchases from the tax it collects on sales, so tax is only paid on the value added."),
    ("e-wallet", "An e-wallet (digital wallet) stores payment information on a phone or online account so customers can pay by QR code, NFC or app. Adoption is driven by perceived usefulness, ease of use, trust, security and social influence."),
    ("buy now pay later", "Buy-now-pay-later (BNPL) lets customers split a purchase into interest-free instalments. Research on Chinese e-wallets found BNPL expands credit to consumers with limited access to credit cards and increases consumption."),
    ("payment method analysis", "Payment method analysis studies how customers pay - cash, card, e-wallet or BNPL - and how the mix affects basket size, processing fees and customer behaviour."),
    ("technology acceptance model", "The Technology Acceptance Model (TAM) explains adoption of a technology such as e-wallets through perceived usefulness and perceived ease of use, which shape attitude and intention to use."),
    ("customer demographics", "Customer demographics such as age, gender, income, marital status and household size explain differences in shopping frequency, basket value and preferred categories, and are used for targeted marketing."),
    ("gender and shopping behaviour", "Research on e-commerce shows gender influences product preferences, impulse buying, sensitivity to reviews and promotions, and preferred payment methods, though differences vary by category and culture."),
    ("quantity sold tracking", "Tracking quantity sold over time by product, store and week shows demand patterns, seasonality and the effect of promotions, and is the input for replenishment and forecasting."),
    ("stock keeping unit", "A stock keeping unit (SKU) is a unique code for each distinct product and pack size that a retailer stocks, used to track inventory and sales."),
    ("sales per square foot", "Sales per square foot measures store productivity: total sales divided by selling floor area."),
    ("conversion rate", "Conversion rate is the share of visitors who make a purchase. In stores it is transactions divided by footfall; online it is orders divided by sessions."),
    ("shrinkage", "Shrinkage is inventory lost to theft, damage, spoilage or administrative error, measured as a percentage of sales. It directly reduces gross margin."),
    ("design thinking", "Design thinking is a human-centred problem-solving process with five stages: Empathise, Define, Ideate, Prototype and Test. In this project it was used to identify retail analytics needs and build an SLM that answers them."),
]

IDENTITY = [
    (["Who are you?", "What is your name?", "Introduce yourself."],
     "I am SuperMart SLM, a small language model trained from scratch with a Qwen3-style architecture to answer questions about supermarket retail analytics - sales, products, discounts, customer demographics, margins, pricing, payments and tax."),
    (["What can you do?", "How can you help me?"],
     "I can summarise sales by department, product category, store, week and hour; describe discounts, coupon use and promotions; compare customer segments by age, income and household type; and explain retail concepts such as gross margin, markup, RFM segmentation, unit price, GST and payment methods."),
    (["How were you trained?", "What data were you trained on?"],
     "I was pre-trained on general English text, then on retail research papers and insights computed from 2.6 million supermarket transaction lines, and finally fine-tuned on question-answer pairs generated from that data."),
]


def split_and_write(qa, val_frac):
    train, val = [], []
    for it in qa.items:
        h = int(hashlib.md5(it["group"].encode()).hexdigest(), 16) % 1000
        rec = {"messages": [{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": it["q"]},
                            {"role": "assistant", "content": it["a"]}],
               "source": it["source"], "group": it["group"]}
        (val if h < val_frac * 1000 else train).append(rec)
    for name, rows in [("sft_train.jsonl", train), ("sft_val.jsonl", val)]:
        with open(os.path.join(DATA, name), "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return train, val


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(ROOT, "combined_supermarket_data.csv"))
    ap.add_argument("--docs", default=os.path.join(ROOT, "design_thinking_merged.jsonl"))
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--skip-transactions", action="store_true", help="do not write the basket-text corpus")
    args = ap.parse_args()
    os.makedirs(os.path.join(DATA, "stats"), exist_ok=True)

    qa, stats, insight_paragraphs, corpus = QA(), {}, [], []

    docs = [json.loads(l) for l in open(args.docs, encoding="utf-8") if l.strip()]
    if any("aliases" not in d for d in docs):
        raise SystemExit("Run scripts/clean_jsonl.py first (documents are not de-duplicated).")
    build_doc_qa(docs, qa, corpus)

    df = load_csv(args.csv)
    build_csv_qa(df, qa, stats, insight_paragraphs)
    if not args.skip_transactions:
        build_transaction_corpus(df, os.path.join(DATA, "transactions_corpus.txt"))

    for term, definition in GLOSSARY:
        qa.add(f"gloss:{term}", [f"What is {term}?", f"Explain {term}."], definition, "glossary")
        corpus.append({"text": f"{term[0].upper() + term[1:]}: {definition}", "source": "glossary"})
    for qs, a in IDENTITY:
        qa.add(f"id:{qs[0]}", qs, a, "identity")

    corpus.append({"text": "\n".join(insight_paragraphs), "source": "supermarket_csv_insights"})
    with open(os.path.join(DATA, "pretrain_corpus.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for r in corpus:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    train, val = split_and_write(qa, args.val_frac)
    with open(os.path.join(DATA, "stats", "dataset_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))

    print(f"pretrain corpus : {len(corpus)} records, {sum(len(r['text']) for r in corpus):,} chars")
    print(f"SFT             : {len(train)} train / {len(val)} val conversations "
          f"({len({i['group'] for i in qa.items})} distinct facts)")
    print(f"stats           : data/stats/dataset_stats.json")


if __name__ == "__main__":
    main()
