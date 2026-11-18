Tax Engine
This document will help you learn how to
import and modify tax configurations from a
Lifecycle Services asset library.
Demo script
Leo Guo and Saurabh Suhasaria
December 2016
Send feedback.
Learn more about Microsoft Dynamics 365.
| Dynamics 365 for Operations

Contents
Concepts 4
General 4
Tax applicability 4
Tax calculation 5
Key model attributes that should be assigned for calculation 5
Tax accounting 6
Tax credit pool 7
Set-off rule 7
Prerequisites 8
Import the configuration from LCS 8
Define the tax configuration for GST 8
Define a tax setup 9
Scenario 1: Tax configuration 10
Task 1.1: Configure a GST tax type and tax components 10
Task 1.2: Configure measures 11
Task 1.3: Configure tax applicability lookups 12
Task 1.4: Configure rate/percentage lookups 13
Task 1.5: Configure formulas 13
Task 1.6: Configure a posting profile 14
Task 1.7: Configure accounting lookups (Optional) 14
Task 1.8: Configure a credit pool 15
Task 1.9: Configure a tax period lookup (Optional) 15
Task 1.10: Complete the tax document configuration 16
Scenario 2: Tax setup 16
Task 2.1: Tax setup 16
Task 2.2: Map configuration tax types to ERP tax types 16
Task 2.3: Set up tax accounting periods 17
Task 2.4: Set up main accounts 18
Task 2.5: Set up rate and percentage tables 18
Scenario 3: Transaction entry 19
Task 3.1: Sales – Free text invoice 19
Sales – Free text invoice: CGST and SGST 19
Sales – Free text invoice: IGST 20
Tax Engine 2

Task 3.2: Purchase – Purchase order, product receipt, and purchase invoice 20
Purchase – Purchase order: CGST and SGST 20
Purchase – Product receipt: CGST and SGST (Optional) 21
Purchase – Purchase invoice: CGST and SGST 21
Purchase – Purchase order: IGST 21
Purchase – Product receipt: IGST (Optional) 22
Purchase – Purchase invoice: IGST 22
Scenario 4: Tax settlement 22
Task 4.1: Confirm that the TIN is one field in the tax credit pool 22
Task 4.2: Run the tax settlement and confirm the result 24
Task 4.3: Specify the set-off rules and run the tax settlement 27
Tax Engine 3

Tax Engine
This document will help you learn how to import and modify tax configurations from a Microsoft Dynamics Lifecycle
Services (LCS) asset library. The new Tax Engine is an essential part of the configurable business application
experience in Microsoft Dynamics 365 for Operations. The new Tax Engine is highly customizable and lets the
business user, a functional consultant, or a power user configure tax rules that determine tax applicability, tax
calculation, posting, and settlement, based on legal and business requirements.
Concepts
This section explains some important concepts that are used throughout this document.
General
● Taxable document – Any transaction that is a candidate for tax, even though the result might be a document
that has no taxes. Examples include a vendor invoice and a customer invoice.
● Tax document – A transaction that has tax details (lines and amounts), and where the tax amount is distributed
in such a way that it’s ready for consumption by any accounting system/framework.
● Taxable document model – An Electronic reporting (ER) model that is mapped to all the Microsoft Dynamics 365
for Operations taxable documents. Currently, we plan to have only one model. This model is the input to the Tax
Engine.
● Tax document model – A taxable document model that includes all possible tax types that the tax document can
be subject to, together with the configuration that is required to derive tax details such as tax applicability, the tax
rate, the tax amount and its distribution, and the accounting structure.
● Taxable document type – All the types of taxable document that the underlying enterprise resource planning
(ERP) system recognizes. For example, Microsoft Dynamics AX has approximately 39 taxable document types.
Tax applicability
● Tax type – A tax type is analogous to a tax regime. Sales tax and value-added tax (VAT) are common example of
sales tax types. Tax types are applicable only when certain conditions (applicability rules) are met.
● Tax components – Tax components are like sub-tax types that a tax authority can levy within the same
jurisdiction or a different jurisdiction. For example, in US, sales tax is levied at different levels of jurisdiction, such
as the state, country, or city level. Different tax components might have a different treatment from accounting, tax
reporting, tax settlement, and other perspectives.
Tax Engine 4

Tax calculation
● Measures – The computation blocks for tax calculation. Measures can be of different types (measure types) that
have different behavior and are used for different computational purposes. The following measure types are
available:
● Base Amount – This measure type should be used to hold the amount that is the basis for tax calculation.
Typically, Base Amount × Rate = Tax Amount.
● Rate – This special measure type is used to provide the applicable tax rate. It’s a compound measure type and
can also be used to hold threshold amount values, as required.
● Tax Amount – Typically, Tax Amount = Base Amount × Rate. This amount should then be distributed for
accounting purposes as required.
● Amount – This measure type should be used for distributed tax amounts, such as the tax recoverable amount
or load on inventory amount.
● Percentage – This simple measure type holds any percentage values. Typically, this measure type should be
used for cases such as load on Inventory percentage or expense percentage.
● Formulas – After the measures have been defined, they can be used to author the tax calculation formulas. These
formulas can be created in two notations:
● Simple assignment notation – For normal scenarios
● Advanced linear equations – Specifically for price-inclusive tax calculation scenarios, such as Maximum Retail
Price (MRP)
Formulas might have to be used conditionally. In this case, the user should add appropriate business conditions.
Key model attributes that should be assigned for calculation
The following table lists reserved keywords for attributes. When you create a new taxable document model, make
sure that you define the model’s attributes as shown here.
Attribute name Data type
Price includes tax Real
Tax amount included in price Real
Line tax amount Real
The following attributes are available in the Taxable Document (India) model that is provided by Microsoft:
● Price includes tax – This attribute resembles a flag that tells the Tax Engine that the tax amount is included in the
line amount.
● Tax amount included in price – The tax amount that should be considered as included in the price, per the
business practice or statutory laws. The Tax Engine uses this value to determine the invoice line amount and the
amount that should be considered during accounting.
● Line tax amount – The tax amount that is computed for the line. This value will remain the same across price-
inclusive and price-exclusive scenarios. Typically, withholding tax amounts should not be considered while this
attribute is initialized.
Tax Engine 5

The following examples show how these attributes should be initialized and used in the tax document configuration.
Price-inclusive scenario
'Price includes tax' = 1.0
'Line tax amount'=CGST.'Tax Amount' + 'SGST'.'Tax Amount' + 'IGST'.'Tax Amount'
'Tax amount included in price'=CGST.'Tax Amount' + 'SGST'.'Tax Amount' + 'IGST'.'Tax Amount'
Price-exclusive scenario
'Price includes tax' = 0.0
'Line tax amount'=CGST.'Tax Amount' + 'SGST'.'Tax Amount' + 'IGST'.'Tax Amount'
For the price-exclusive scenario, the Tax Engine implicitly initializes the Tax amount included in price attribute to 0
(zero). Therefore, the equation doesn’t have to be written explicitly.
Tax accounting
● Tax accounting provider – The sub-ledger that is affected in the tax accounting scenario. For example, in the
purchase flow, if tax must be paid to the vendor as part of the vendor invoice, the tax accounting provider will be
Party/Vendor. This list depends on the underlying ERP system. For Microsoft Dynamics AX, the following providers
are currently supported:
● Party (vendor or customer only)
● Inventory
● Tax
● Ledger
● Posting types – When the tax sub-ledger is affected as part of the tax accounting process, the tax amount must
no longer be trusted for settlement, reporting, costing, and similar purposes. This list can also vary, depending on
country/region-specific regulations that are based on tax types. For India, the following posting types are
supported:
● Tax Recoverable
● Tax Payable
● Tax Expense
● Deferred Tax Recoverable
● Interim Tax Payable
● Interim Tax Recoverable
Tax Engine 6

Tax credit pool
The following illustration shows the configuration of tax recoverable and tax payable amounts.
Tax credit pool
Tax type
Tax component
|     | GST | CGST | GSTIN |
| --- | --- | ---- | ----- |
SGST
IGST

When this configuration is used, the tax recoverable and tax payable amounts will be accumulated on each tax credit
pool. For example, if the GST registration number is ABCDE1234DXL001, the tax recoverable amount will be
accumulated as shows in the following table.
| Tax type  | Tax component  | GSTIN            | Amount    |
| --------- | -------------- | ---------------- | --------- |
| GST       | CGST           | ABCDE1234DXL001  | Amount 1  |
|           |                | ABCDE1234DXL002  | Amount 2  |
|           | SGST           | ABCDE1234DXL001  | Amount 3  |
|           |                | ABCDE1234DXL002  | Amount 4  |
|           | IGST           | ABCDE1234DXL001  | Amount 5  |
|           |                | ABCDE1234DXL002  | Amount 6  |
Set-off rule
The set-off rule indicates how the excess tax recoverable should be used to set off the excess tax payable. The
following tables give more details.
Before rule-based settlement
| Tax type  |     | Tax amount                         |     |
| --------- | --- | ---------------------------------- | --- |
| CGST      |     | 10,000 – 4,000 = 6,000 tax credit  |     |
| SGST      |     | 8,000 – 3,200=4,800 tax credit     |     |
After rule-based settlement
| Tax type   |     | Tax amount                        |     |
| ---------- | --- | --------------------------------- | --- |
| IGST-CGST  |     | 14,400 – 6,000 = 8,400 tax debit  |     |
| IGST-SGST  |     | 8,400 – 4,800 = 3,600 payment     |     |
Tax Engine  7

Prerequisites
1 ER has been configured.
2 Switch to the INMF company context.
Import the configuration from LCS
1 Navigate to the Localization configurations workspace.
2 Click Repositories.
3 Click Add, select the LCS option, and then click Create repository.
4 In the Configuration repository properties dialog box, click OK.
A new repository that is named LCS is created.
5 Select the newly created repository, and click Open.
6 Click Tax (India GST), and select the latest version (34.65.47).
7 Click Import.
8 Click Yes in the message boxes.
The Taxable Document, Taxable Document (India), and Tax (India GST) configuration documents should be
imported.
9 Close the page, and navigate back to the Localization configurations workspace.
Define the tax configuration for GST
1 Configure a taxable document model or use the Microsoft/partner-provided taxable document model.
2 Extend the taxable document model by using another taxable document model to support specific
country/region-specific or state-specific tax requirements, as required. Again, you can use the Microsoft/partner-
provided country/region-specific taxable document.
3 Any attribute that is relevant to any of the tax pillars (tax applicability, calculation, posting, or settlement) should
form part of one of the taxable document models, based on the scope of the attribute.
Tax Engine 8

4 Configure the tax document model by extending the next-to-last taxable document model.
The tax document model should have the following characteristics:
● Applicability:
● All the applicable tax types
● All the applicable tax components
● Applicability rules for the tax types and tax components
● Formulas:
● Rate and Percentage measure types, and any lookup structures
● All the tax calculation logic for all the tax types and tax components, together with any conditions
● All the tax distribution formulas, together with any conditions
● Accounting:
● Define the accounting treatment for the computed tax amount and distributed tax amounts, together with
the conditions when this accounting treatment should be applied.
● For the lookup, define attributes that the business uses to determine the main account that the distributed
tax amounts should be accounted to.
Define a tax setup
1 Go to Tax > Setup > Tax configuration > Tax setup.
2 Enter a tax setup name, a description, and the configuration to use.
3 In the Companies grid, add the companies that will use this tax configuration.
4 Click Synchronize. Synchronization will let you complete the required tax setup.
5 Select the company, and then click the Setup link.
6 Expand the Header and Lines nodes.
The left side of the page shows all the applicable taxes that are configured as part of the tax document.
7 Click the tax type node to set up Accounting and Tax type mapping.
8 Expand the tax type node to see the tax components.
9 Click the tax component node to set up Accounting and Tax period mapping.
10 Expand the tax component node to see the tax measures, such as tax rate and load on inventory percentage.
11 Click the Rate nodes to complete the rate table.
12 Confirm that Accounting and Tax period mapping appear as tabs on the right side of the page.
13 Click Save.
The tax configuration is now ready to use.
Tip: We recommend that you set up the tax accounts at the tax component level.
Tax Engine 9

Scenario 1: Tax configuration
Contoso manufactures and sells goods and services in India, and these transactions are subject to several taxes. In
this exercise, you will learn how to configure Contoso’s tax requirements for the Goods and Services Tax (GST) tax
type by using the new tax solution.
Task 1.1: Configure a GST tax type and tax components
1 Create a tax configuration.
2 Click the tax document.
3 Click Designer to open the tax document, and configure the tax type and tax components.
4 Click the Lines node.
5 Click Add to create a tax type.
6 Enter the required details.
Tax Engine 10

7 Click the newly created tax type, and then click Add to create the tax components.
8 Save the tax document, and close the designer.
Task 1.2: Configure measures
1 Open the tax document that you created in the previous task by clicking Designer.
2 Expand the Tax document tree, and click the tax component to create a measure for.
3 Click Add.
4 Add a new measure, or select an existing measure in the list.
5 Enter the measure type for the new measure.
Tax Engine 11

6 Save the tax document, and close the designer.
Task 1.3: Configure tax applicability lookups
1 Open the tax document that you created earlier by clicking Designer.
2 Expand the Tax document tree, and click a GST tax type.
The Tax Applicability lookup tab is available only for nodes at this level.
3 Click Columns. A list of attributes that are relevant to the tax type/tax component applicability appears.
4 Select the relevant attributes.
GST
Tax Engine 12

CGST and SGST
5 Click Add to enter the relevant conditions for the tax type/tax component applicability condition.
6 Save the tax document, and close the designer.
Task 1.4: Configure rate/percentage lookups
1 Open the tax document that you created earlier by clicking Designer.
2 Expand the Tax document tree, and expand the tax component node.
3 Select the measure of the Rate/Percentage type to create a rate/percentage lookup.
4 Click Columns. A list of attributes that are relevant to the tax rate/percentage value appears.
5 Select the relevant attributes.
Don’t click Add. Values that you enter here have no effect on the actual rate table. This table should be
completed from Tax > Tax configuration > Tax setup.
6 Save the tax document, and close the designer.
Task 1.5: Configure formulas
Formulas can be configured at the level of either group nodes (line, tax component, or tax type) or measure nodes.
We recommend that you always configure tax calculation formulas at the group node level. You can configure tax
amount distribution formulas at either the group node level or the measure node level.
1 Open the tax document that you created earlier by clicking Designer.
2 Expand the Tax document tree, and expand the tax component node.
3 Select the tax component node, and then click the Formulas tab.
4 Click Add Tax formula.
5 In the Details section, click Edit (the pencil button) to enter the formula and any condition.
For our example, add the following formulas:
● 'Base Amount'=Lines.'Base Amount'
● 'Tax Amount'='Base Amount'*'Rate'
Tax Engine 13

6 Optional: Enter a description for the formula.
7 Save the tax document, and close the designer.
Task 1.6: Configure a posting profile
Only tax component nodes support a posting profile definition.
1 Open the tax document that you created earlier by clicking Designer.
2 Expand the Tax document tree, and expand the tax component node.
3 Select the tax component node, and then click the Postings tab.
4 Click Add Posting Profile to create a posting profile definition.
5 Enter the accounting treatment for the various tax measures that you defined in the previous task.
6 Enter the names of debit and credit accounting sub-ledgers, and map these sub-ledgers to the appropriate
accounting provider.
For example, for a sales transaction, the accounting treatment for the Tax Amount measure will resemble the
following illustration.
7 Optional: Enter a description for the posting profile.
8 Save the tax document, and close the designer.
Task 1.7: Configure accounting lookups (Optional)
Only tax type and tax component nodes support an accounting lookup definition.
1 Open the tax document that you created earlier by clicking Designer.
2 Expand the Tax document tree, and select the tax type or tax component node.
Tax Engine 14

3 Click Columns. A list of attributes that can be used to determine the main accounts that will be used to account
taxes appears.
4 Select the relevant attributes.
Don’t click Add. Values that you enter here have no effect on the actual tax main accounts decision table. This
table should be completed from Tax > Tax configuration > Tax setup.
5 Save the tax document, and close the designer.
Task 1.8: Configure a credit pool
Only tax component nodes support a posting profile definition.
1 Open the tax document that you created earlier by clicking Designer.
2 Expand the Tax document tree, and select the tax component node to define the settlement rule for.
3 Click the Credit pool tab.
4 Click Columns. A list of attributes that are relevant to the tax settlement of this component appears. For example,
this might be the appropriate tax registration number.
5 Select the relevant attributes.
Don’t click Add. Values that you enter here have no effect on the actual rate table. This table should be
completed from Tax > Tax configuration > Tax setup.
6 Save the tax document, and close the designer.
Task 1.9: Configure a tax period lookup (Optional)
Only tax component nodes support a tax period lookup definition.
1 Open the tax document that you created earlier by clicking Designer.
2 Expand the Tax document tree, and select the tax component node to define the tax period lookup for.
3 Click the Tax period tab.
4 Click Columns. A list of attributes that are relevant to the tax period of this component appears. For example, this
might be the appropriate tax registration number. For example, tax authorities and periods might have to be
defined for each state. In this case, the same GST setup must be mapped to multiple tax authorities and periods.
5 Select the relevant attributes.
Don’t click Add. Values that you enter here have no effect on the actual rate table. This table should be
completed from Tax > Tax configuration > Tax setup.
6 Save the tax document, and close the designer.
Tax Engine 15

Task 1.10: Complete the tax document configuration
1 After you’ve completed all the previous tasks, in the Localization configurations workspace, click Change
status.
2 If there are any errors, open the designer, click Validate, and fix the errors.
3 Complete the tax document configuration.
After the status is updated to Complete, the configuration is ready for deployment.
Scenario 2: Tax setup
Task 2.1: Tax setup
A single tax configuration can be used for multiple companies that share the same tax jurisdiction. To deploy a tax
configuration, follow these steps.
1 Go to Tax > Tax configuration > Tax setup.
2 Click New.
3 Enter a name and description, and select the configuration to use. This configuration should be the configuration
that you created earlier.
4 On the Companies FastTab, click New.
5 Select the appropriate company, and save your changes.
6 Click Synchronize. The required configuration is deployed for you.
7 Click Setup to complete the required tax setup, such as the mapping of the tax settlement (accounting) periods,
tax main accounts, and rate and percentage tables.
Task 2.2: Map configuration tax types to ERP tax types
1 Click Setup.
2 Select the tax type node to map to the tax type on the ERP system.
Tax Engine 16

3 Click the Tax type mapping tab.
4 Select the appropriate tax type.
5 Click Save.
Task 2.3: Set up tax accounting periods
1 Click Setup.
2 Select and expand the tax type nodes.
3 Select the tax component node to set up the settlement period for.
4 Click the Tax period mapping tab.
5 Select the appropriate tax settlement period.
6 Click Save.
Tax Engine 17

Task 2.4: Set up main accounts
1 Click Setup.
2 Select and expand the tax type nodes.
3 Select the tax type or tax component to set up the main accounts for.
4 Click the Accounting tab. The accounts list is generated dynamically, based on the posting profile setup.
5 Select the appropriate main accounts.
6 Click Save.
Note: The value at the tax component level will override the value at the tax type level. If the value is left blank for a
posting type at the component level, the corresponding value from the tax type level will be used for posting.
The following illustration shows the tax main account setup for GST.
Task 2.5: Set up rate and percentage tables
1 Click Setup.
2 Select and expand a tax type node.
3 Select and expand the tax component node to set up the tax rate and percentage values for.
4 Select a tax rate/percentage node. The rate/percentage table appears on the right side of the page.
5 Complete the rate/percentage table.
6 Click Save.
Tip: We recommend that you leave one row that has a value only for the tax rate. This value will be used as the
default rate. As you become more comfortable, you can add more rows to the rate table.
Tax Engine 18

The following illustration shows the rate setup for CGST.
You’ve now completed the tasks for this scenario. You can now test your configuration and tax setup by entering
transactions.
Scenario 3: Transaction entry
Task 3.1: Sales – Free text invoice
1 Make sure that you’re in the appropriate company context. For India, select INMF.
2 Go to Accounts receivable > Invoices > All free text invoices.
3 Enter a free text invoice.
Sales – Free text invoice: CGST and SGST
1 Select customer account INMF-000001. CGST and SGST will be applied for other customers only if those
companies are both located in the same state as Contoso.
2 Enter main account 401100. (You can use any other account instead.)
3 Enter the quantity and amount.
4 Click Save. The Tax information button on the Lines FastTab becomes available.
5 Click Tax information.
6 Click the tax document to review the taxes that were applied and the tax calculation results.
7 Click Post to account the invoice.
Tax Engine 19

Sales – Free text invoice: IGST
1 Select customer account INMF-000002. IGST will be applied for other customers only if those customers are
both located in a different state.
2 Enter main account 401100. (You can use any other account instead.)
3 Enter the quantity and amount.
4 Click Save. The Tax information button on the Lines FastTab becomes available.
5 Click Tax information.
6 Click the tax document to review the taxes that were applied and the tax calculation results.
7 Click Post to account the invoice.
Tips:
● If a tax-related attribute is modified, use the Recalculate button on the tax document to manually recalculate
taxes.
● You can use the Tax applicability button to override system-determined applicability. Select the line to override
the system-determined tax applicability for, and then click Tax applicability. Select the appropriate tax type and
tax components, and then click OK. Use the Recalculate button to review the results.
Task 3.2: Purchase – Purchase order, product receipt, and purchase
invoice
1 Make sure that you’re in the appropriate company context. For India, select INMF.
2 Go to Accounts payable > Purchase orders > All purchase orders.
3 Enter a purchase order.
Purchase – Purchase order: CGST and SGST
1 Select vendor account INMF-000001. For CGST and SGST to be applied, the Contoso warehouse must be in the
state of Karnataka. Therefore, select site 3 and the Bangalore warehouse.
2 Select item 1104. Enter a quantity of 1 and an amount of 1,00,000. Save.
3 Click Save. The Tax information button on the Lines FastTab becomes available.
4 Click Tax information.
5 Select Schedule IV as the VAT schedule. If you leave this field blank, VAT won’t be applied.
The VAT schedule also determines the tax rate that is applied, based on your rate table setup.
Tax Engine 20

6 Click the tax document to review the taxes that were applied and the tax calculation results.
If you accepted the default values and have completed the setup as described in the previous tasks, you should
see the following values:
● CGST tax rate: 10%
● Tax amount: 10,000
7 Confirm the purchase order.
Purchase – Product receipt: CGST and SGST (Optional)
1 Click the Receive menu item to receive the goods against this purchase order.
2 You can receive either the whole purchase order or part of it.
3 Make sure that the tax document is generated based on the quantities on the product receipt, not the quantities
on the purchase order.
Purchase – Purchase invoice: CGST and SGST
1 Click the Invoice menu item to create a purchase invoice for the goods against this purchase order.
2 You can invoice either the whole purchase order or part of it.
3 Make sure that the tax document is generated based on the quantities on the product receipt, not the quantities
on the purchase order.
4 Click the tax document to review the taxes that were applied and the tax calculation results.
5 Click Post to account the invoice.
Purchase – Purchase order: IGST
1 Select vendor account INMF-000001. For IGST to be applied, the Contoso warehouse must be in any state except
Karnataka. Therefore, select site 2 and the Mumbai warehouse.
2 Select item 1104. Enter the quantity and amount.
3 Click Save. The Tax information button on the Lines FastTab becomes available.
4 Click Tax information.
5 Select Schedule IV as the CST schedule (proxy attribute). If you leave this field blank, CST won’t be applied.
The CST schedule also determines the tax rate that is applied, based on you rate table setup.
6 Click Purchase, and then click the Tax document to review the taxes that were applied and the tax calculation
results.
If you accepted the default values and have completed the setup as described in the previous tasks, you should
see the following values:
● IGST tax rate: 18%
● Tax amount: Assessable value * Rate
7 Confirm the purchase order.
Tax Engine 21

Purchase – Product receipt: IGST (Optional)
1 Click the Receive menu item to receive the goods against this purchase order.
2 You can receive either the whole purchase order or part of it.
3 Make sure that the tax document is generated based on the quantities on the product receipt, not the quantities
on the purchase order.
Purchase – Purchase invoice: IGST
1 Click the Invoice menu item to create a purchase invoice for the goods against this purchase order.
2 You can invoice either the whole purchase order or part of it.
3 Make sure that the tax document is generated based on the quantities on the product receipt, not the quantities
on the purchase order.
4 Click the tax document to review the taxes that were applied and the tax calculation results.
5 Click Post to account the invoice.
Tips:
● If a tax-related attribute is modified, use the Recalculate button on the tax document to manually recalculate
taxes.
● You can use the Tax applicability button to override system-determined applicability. Select the line to override
the system-determined tax applicability for, and then click Tax applicability. Select the appropriate tax type and
tax components, and then click OK. Use the Recalculate button to review the results.
Scenario 4: Tax settlement
Task 4.1: Confirm that the TIN is one field in the tax credit pool
Estimated time to complete this task: 10 minutes
For this task, you will play the role of a system administrator at Contoso Entertainment System India. You’ve been
asked to configure the tax identification number (TIN) as a tax credit pool for CGST, SGST, and IGST.
In this task, you will examine whether the TIN is configured as a tax credit pool on the released configuration.
1 Start Dynamics 365 for Operations:
a Start Internet Explorer.
b Click the Dynamics 365 for Operations shortcut. Alternatively, in the Address bar, enter the URL that the
instructor shared with you.
c Enter the credentials that the instructor shared with you.
2 Click Organization administration > Electronic reporting.
Tax Engine 22

3 In the Localization configurations workspace, click Tax configurations.
4 On the Configurations page, select Tax (India) as the taxable document, and then click Designer to open
Operation designer.
Tax Engine 23

5 In Operation designer, in the Tax document tree, select the CGST node, and then click the Credit pool tab.
Confirm that Tax Identification Number is already configured as one of the columns.
6 Click Columns, and verify that the selections in the Selected columns and Available columns are correct for the
tax credit pool that you’re constructing. You can modify the columns by moving them between the Available
columns and Selected columns fields. Click OK to save your changes and close this dialog box.
Note: If you made any changes, you must complete the configuration before those changes can take effect.
Task 4.2: Run the tax settlement and confirm the result
Estimated time to complete this task: 10 minutes
Tax Engine 24

This task assumes that you’ve already completed Error! Reference source not found..
For this task, you will play the role of an accountant.
When the set-off rule is configured, the settlement process will be able to run across different tax credit pools.
The following illustration outlines the procedure for availing the ITC (Input Tax Credit).
You will configure the set-off rule to use the excess CGST/SGST/IGST recoverable to set off the CGST/SGST/IGST
payable.
1 Go to Tax > Setup > Tax configuration > Tax setup.
2 Click Setoff rules.
Tax Engine 25

3  Click New, and enter a name for the new set-off rule.

4  Add the following information to the rules.
| Name  | FastTab       | Path                       |
| ----- | ------------- | -------------------------- |
| CGST  | Recoverables  | Tax document – GST – CGST  |
|       | Payables      | Tax document – GST-CGST    |
Tax document – GST-IGST

| Name  | FastTab       | Path                       |
| ----- | ------------- | -------------------------- |
| IGST  | Recoverables  | Tax document – GST – IGST  |
|       | Payables      | Tax document – GST-IGST    |
Tax document – GST-CGST
Tax document – GST-SGST
Tax Engine  26

Task 4.3: Specify the set-off rules and run the tax settlement
Estimated time to complete this task: 10 minutes
This task assumes that you’ve already completed Task 4.1: Confirm that the TIN is one field in the tax credit pool and
Task 4.2: Run the tax settlement and confirm the result.
1 Go to Tax > Declarations > Settle and post sales tax.
2 Specify the following parameters, and then click OK.
Parameter Value
Settlement period GST
Tax type GST
Registration number 19725874156
Tax setoff rules Select CGST;SGST;IGST.
From date 10/1/2016
To date 10/31/2016
3 Confirm the result.
Note: You can confirm that part of the CGST/SGST/IGST payable was set off by the excess CGST/SGST/IGST
recoverable, per the rule setup.
4 Click Transactions.
Note: On the Transactions page, you can view the settlement details by transaction. Therefore, you can more
accurately track how the settlement was processed.
Tax Engine 27

Send feedback. © 2016 Microsoft Corporation. All rights
reserved.
Microsoft Dynamics is a line of integrated, adaptable business
management solutions that enables you and your people to make This document is provided “as-is.”
business decisions with greater confidence. Microsoft Dynamics works Information and views expressed in this
like and with familiar Microsoft software, automating and streamlining document, including URL and other
financial, customer relationship, and supply chain processes in a way Internet Web site references, may
that helps you drive business success. change without notice. You bear the risk
of using it.
United States and Canada toll-free: (888) 477-7989
Some examples are for illustration only
Worldwide: (1) (701) 281-6500
and are fictitious. No real association is
www.microsoft.com/dynamics
intended or inferred.
This document does not provide you
with any legal rights to any intellectual
property in any Microsoft product. You
may copy and use this document for
your internal, reference purposes.