import streamlit as st
import pandas as pd
from datetime import datetime
import re
import random
import string
import io

# ======================
# Page Config
# ======================
st.set_page_config(
    page_title="Cashflow Currency Converter",
    page_icon="💱",
    layout="wide"
)

# ======================
# Approximate Exchange Rates (to USD as base)
# Update these rates for production use
# ======================
RATES_TO_USD = {
    "USD": 1.0,
    "HKD": 0.1282,      # ~7.80 HKD = 1 USD
    "SGD": 0.755,       # ~1.32 SGD = 1 USD
    "CNY": 0.138,
    "EUR": 1.08,
    "GBP": 1.27,
    "JPY": 0.0067,
    "AUD": 0.65,
    "CAD": 0.73,
    "INR": 0.012,       # ~83.3 INR = 1 USD
    "KRW": 0.00073,     # ~1370 KRW = 1 USD
}

SUPPORTED_TARGET = ["HKD", "SGD", "USD"]

# ======================
# Standard Categories (for reference)
# ======================
RECEIPT_CATEGORIES = [
    "AR Receipt",
    "Finance Loan Support",
    "Intercompany Support",
    "Other Receipt",
]

PAYMENT_CATEGORIES = [
    "General expense",
    "Rent",
    "Taxes & dues",
    "Intercompany",
    "Payroll",
    "CAPEX",
    "Professional fees",
    "Financing",
    "Other Payment",
]

ALL_STANDARD_CATEGORIES = RECEIPT_CATEGORIES + PAYMENT_CATEGORIES

# ======================
# Helper Functions
# ======================
def is_valid_email(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email.strip()))

def generate_verification_code(length=6):
    return "".join(random.choices(string.digits, k=length))

def normalize_currency(code) -> str:
    if pd.isna(code) or str(code).strip() == "":
        return "USD"
    code = str(code).strip().upper()
    aliases = {
        "HK$": "HKD", "HK DOLLAR": "HKD", "HONG KONG DOLLAR": "HKD",
        "S$": "SGD", "SINGAPORE DOLLAR": "SGD",
        "US$": "USD", "US DOLLAR": "USD", "DOLLAR": "USD",
        "RMB": "CNY", "CNH": "CNY", "YUAN": "CNY",
        "RS": "INR", "RUPEE": "INR", "INDIAN RUPEE": "INR",
        "WON": "KRW", "KOREAN WON": "KRW",
    }
    return aliases.get(code, code)

def convert_amount(amount, from_currency, to_currency):
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return None

    from_c = normalize_currency(from_currency)
    to_c = normalize_currency(to_currency)

    rate_from = RATES_TO_USD.get(from_c)
    rate_to = RATES_TO_USD.get(to_c)

    if rate_from is None or rate_to is None:
        return None

    amount_usd = amount * rate_from
    return round(amount_usd / rate_to, 2)

def find_column(df_columns, possible_names):
    """Case-insensitive + space-insensitive column finder."""
    lower_map = {str(c).strip().lower().replace(" ", ""): c for c in df_columns}
    for name in possible_names:
        key = name.lower().replace(" ", "")
        if key in lower_map:
            return lower_map[key]
    return None

def process_dataframe(df: pd.DataFrame, target_currency: str):
    warnings = []

    # Clean completely empty rows
    df = df.dropna(how="all").copy()

    # Column mapping – includes your exact column names
    col_map = {
        "company": [
            "entity", "company", "company name", "comp", "entity name"
        ],
        "party": [
            "organization", "party name", "party", "customer name", "customer",
            "payee name", "payee", "vendor", "supplier", "organisation"
        ],
        "currency": [
            "currency", "curr", "ccy", "fx"
        ],
        "amount": [
            "amount", "amt", "value", "transaction amount"
        ],
        "payment_date": [
            "payment date", "date", "txn date", "transaction date", "pay date"
        ],
        "category": [
            "category", "categories", "type", "transaction type", "class"
        ],
    }

    found = {}
    for key, candidates in col_map.items():
        col = find_column(df.columns, candidates)
        if col:
            found[key] = col
        else:
            warnings.append(f"Could not find column for: **{key.replace('_', ' ').title()}**")

    required = ["amount", "currency"]
    missing_required = [r for r in required if r not in found]
    if missing_required:
        return None, [f"Missing required column(s): {', '.join(missing_required)}"]

    # Build result
    result = pd.DataFrame()
    result["Company"] = df[found["company"]].astype(str).str.strip() if "company" in found else ""
    result["Party Name"] = df[found["party"]].astype(str).str.strip() if "party" in found else ""
    result["Currency"] = df[found["currency"]].apply(normalize_currency)
    result["Amount"] = pd.to_numeric(df[found["amount"]], errors="coerce")
    result["Payment Date"] = (
        pd.to_datetime(df[found["payment_date"]], errors="coerce")
        if "payment_date" in found else pd.NaT
    )
    result["Category"] = (
        df[found["category"]].astype(str).str.strip()
        if "category" in found else ""
    )

    # Remove rows where Amount is completely missing
    result = result.dropna(subset=["Amount"]).reset_index(drop=True)

    # Convert
    converted_col = f"Amount (in {target_currency})"
    result[converted_col] = result.apply(
        lambda row: convert_amount(row["Amount"], row["Currency"], target_currency),
        axis=1
    )

    # Unsupported currencies warning
    unsupported = result[
        result[converted_col].isna() & result["Amount"].notna()
    ]["Currency"].unique()
    if len(unsupported) > 0:
        warnings.append(
            f"Unsupported currencies (left blank): {', '.join(map(str, unsupported))}"
        )

    # Non-standard categories warning (optional)
    non_standard = result[
        ~result["Category"].isin(ALL_STANDARD_CATEGORIES)
        & (result["Category"] != "")
        & (result["Category"].str.lower() != "nan")
    ]
    if len(non_standard) > 0:
        unique_non_std = non_standard["Category"].unique()
        warnings.append(
            f"Non-standard categories found ({len(non_standard)} rows): "
            f"{', '.join(map(str, unique_non_std[:10]))}"
            + ("..." if len(unique_non_std) > 10 else "")
        )

    # Final column order
    cols = ["Company", "Party Name", "Currency", "Amount", converted_col, "Payment Date", "Category"]
    result = result[cols]

    return result, warnings

# ======================
# Session State
# ======================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "verification_code" not in st.session_state:
    st.session_state.verification_code = None
if "pending_email" not in st.session_state:
    st.session_state.pending_email = None
if "code_sent" not in st.session_state:
    st.session_state.code_sent = False

# ======================
# Sidebar - Login
# ======================
st.sidebar.header("🔐 Login with Email")

if not st.session_state.logged_in:
    if not st.session_state.code_sent:
        with st.sidebar.form("email_form"):
            email = st.text_input("Email address", placeholder="you@example.com")
            send_btn = st.form_submit_button(
                "Send Verification Code", use_container_width=True, type="primary"
            )

            if send_btn:
                email = email.strip().lower()
                if not email:
                    st.error("Please enter your email.")
                elif not is_valid_email(email):
                    st.error("Please enter a valid email address.")
                else:
                    code = generate_verification_code()
                    st.session_state.verification_code = code
                    st.session_state.pending_email = email
                    st.session_state.code_sent = True
                    st.rerun()
    else:
        st.sidebar.info(f"Code sent to:\n**{st.session_state.pending_email}**")
        st.sidebar.warning(f"🧪 Demo Code: **{st.session_state.verification_code}**")
        st.sidebar.caption("In a real app this code would be sent by email.")

        with st.sidebar.form("verify_form"):
            user_code = st.text_input("Enter 6-digit verification code", max_chars=6)
            col1, col2 = st.columns(2)
            with col1:
                verify_btn = st.form_submit_button(
                    "Verify & Login", use_container_width=True, type="primary"
                )
            with col2:
                back_btn = st.form_submit_button("← Back", use_container_width=True)

            if back_btn:
                st.session_state.code_sent = False
                st.session_state.verification_code = None
                st.session_state.pending_email = None
                st.rerun()

            if verify_btn:
                if user_code.strip() == st.session_state.verification_code:
                    st.session_state.logged_in = True
                    st.session_state.user_email = st.session_state.pending_email
                    st.session_state.code_sent = False
                    st.session_state.verification_code = None
                    st.session_state.pending_email = None
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Incorrect verification code. Please try again.")
else:
    st.sidebar.success(f"Logged in as:\n**{st.session_state.user_email}**")
    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user_email = None
        st.rerun()

# ======================
# Main App
# ======================
if not st.session_state.logged_in:
    st.title("💱 Cashflow Currency Converter")
    st.info("👈 Please login with your email in the sidebar to continue.")
    st.stop()

st.title("💱 Cashflow Currency Converter")
st.markdown(f"Welcome, **{st.session_state.user_email}**!")

st.markdown("""
Upload your cashflow Excel / CSV (like `mycashflow.xlsx`).  
The app will standardize columns and convert all amounts into **HKD / SGD / USD**.
""")

# Category reference
with st.expander("📋 Recommended Categories (click to expand)", expanded=False):
    col_r, col_p = st.columns(2)
    with col_r:
        st.markdown("**Receipts (positive Amount)**")
        for cat in RECEIPT_CATEGORIES:
            st.markdown(f"- {cat}")
    with col_p:
        st.markdown("**Payments (negative Amount)**")
        for cat in PAYMENT_CATEGORIES:
            st.markdown(f"- {cat}")

# Upload
uploaded_file = st.file_uploader(
    "Upload Excel or CSV file",
    type=["xlsx", "xls", "csv"],
    help="Supports columns: entity, Organization, currency, amount, Payment Date, Category"
)

if uploaded_file is not None:
    try:
        if uploaded_file.name.lower().endswith(".csv"):
            df_raw = pd.read_csv(uploaded_file)
        else:
            df_raw = pd.read_excel(uploaded_file)

        # Remove completely empty rows early
        df_raw = df_raw.dropna(how="all")

        st.success(f"✅ File loaded: **{uploaded_file.name}** ({len(df_raw)} rows)")

        with st.expander("Preview raw data (first 15 rows)"):
            st.dataframe(df_raw.head(15), use_container_width=True)

        st.markdown("---")
        st.subheader("1️⃣ Select Target Currency")

        target_currency = st.selectbox(
            "Convert all amounts to:",
            options=SUPPORTED_TARGET,
            index=0,  # default HKD
            help="All original amounts will be converted into this currency."
        )

        st.caption(
            "Approximate rates (via USD): "
            "HKD ≈ 7.80 | SGD ≈ 1.32 | USD = 1.00 | INR ≈ 83.3 | KRW ≈ 1370"
        )

        if st.button("🔄 Process & Convert", type="primary", use_container_width=True):
            with st.spinner("Processing your cashflow data..."):
                result_df, warnings = process_dataframe(df_raw, target_currency)

            if result_df is None:
                for w in warnings:
                    st.error(w)
            else:
                for w in warnings:
                    st.warning(w)

                st.success(f"✅ Conversion completed! {len(result_df)} valid transactions processed.")

                st.subheader("2️⃣ Processed Data")
                st.dataframe(result_df, use_container_width=True)

                # Summary metrics
                converted_col = f"Amount (in {target_currency})"
                total_converted = result_df[converted_col].sum()

                col1, col2, col3 = st.columns(3)
                col1.metric("Total Rows", len(result_df))
                col2.metric("Sum of original Amount", f"{result_df['Amount'].sum():,.2f}")
                col3.metric(f"Sum in {target_currency}", f"{total_converted:,.2f}")

                # Category breakdown
                st.markdown("#### Category Summary")
                cat_summary = (
                    result_df.groupby("Category", dropna=False)
                    .agg(
                        Count=("Amount", "count"),
                        Original_Sum=("Amount", "sum"),
                        Converted_Sum=(converted_col, "sum"),
                    )
                    .reset_index()
                    .sort_values("Converted_Sum", ascending=False)
                )
                st.dataframe(cat_summary, use_container_width=True)

                # Download
                st.markdown("---")
                st.subheader("3️⃣ Download Result")

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                default_name = f"cashflow_converted_{target_currency}_{timestamp}.xlsx"

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    result_df.to_excel(writer, index=False, sheet_name="Converted")
                    cat_summary.to_excel(writer, index=False, sheet_name="Category Summary")
                output.seek(0)

                st.download_button(
                    label="📥 Download Converted Excel",
                    data=output,
                    file_name=default_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    type="primary",
                )

    except Exception as e:
        st.error(f"Error reading file: {e}")
        st.exception(e)

else:
    st.info("👆 Please upload your cashflow Excel or CSV file to begin.")

# Footer
st.markdown("---")
st.caption("""
**Notes**  
• Amount: **positive** = receipt / inflow, **negative** = payment / outflow  
• Your file columns (`entity`, `Organization`, `currency`, `amount`, `Payment Date`, `Category`) are fully supported  
• Empty rows are automatically skipped  
• Exchange rates are approximate — update `RATES_TO_USD` for production accuracy  
""")
