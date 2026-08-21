import streamlit as st
import pandas as pd
from datetime import datetime
import re
import random
import string
import io
import plotly.express as px

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
# ======================
RATES_TO_USD = {
    "USD": 1.0,
    "HKD": 0.1282,
    "SGD": 0.755,
    "CNY": 0.138,
    "EUR": 1.08,
    "GBP": 1.27,
    "JPY": 0.0067,
    "AUD": 0.65,
    "CAD": 0.73,
    "INR": 0.012,
    "KRW": 0.00073,
}

SUPPORTED_TARGET = ["HKD", "SGD", "USD"]

# ======================
# Standard Categories
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
    lower_map = {str(c).strip().lower().replace(" ", ""): c for c in df_columns}
    for name in possible_names:
        key = name.lower().replace(" ", "")
        if key in lower_map:
            return lower_map[key]
    return None

def process_dataframe(df: pd.DataFrame, target_currency: str):
    warnings = []
    df = df.dropna(how="all").copy()

    col_map = {
        "company": ["entity", "company", "company name", "comp", "entity name"],
        "party": [
            "organization", "party name", "party", "customer name", "customer",
            "payee name", "payee", "vendor", "supplier", "organisation"
        ],
        "currency": ["currency", "curr", "ccy", "fx"],
        "amount": ["amount", "amt", "value", "transaction amount"],
        "payment_date": ["payment date", "date", "txn date", "transaction date", "pay date"],
        "category": ["category", "categories", "type", "transaction type", "class"],
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

    result = result.dropna(subset=["Amount"]).reset_index(drop=True)

    converted_col = f"Amount (in {target_currency})"
    result[converted_col] = result.apply(
        lambda row: convert_amount(row["Amount"], row["Currency"], target_currency),
        axis=1
    )

    unsupported = result[
        result[converted_col].isna() & result["Amount"].notna()
    ]["Currency"].unique()
    if len(unsupported) > 0:
        warnings.append(
            f"Unsupported currencies (left blank): {', '.join(map(str, unsupported))}"
        )

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
The app will standardize columns, convert amounts, and show **payments by payee each month**.
""")

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
            df_raw = pd.read_excel(uploaded_file, engine="openpyxl")

        df_raw = df_raw.dropna(how="all")

        st.success(f"✅ File loaded: **{uploaded_file.name}** ({len(df_raw)} rows)")

        with st.expander("Preview raw data (first 15 rows)"):
            st.dataframe(df_raw.head(15), use_container_width=True)

        st.markdown("---")
        st.subheader("1️⃣ Select Target Currency")

        target_currency = st.selectbox(
            "Convert all amounts to:",
            options=SUPPORTED_TARGET,
            index=0,
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

                # Store in session so chart stays after interaction
                st.session_state.result_df = result_df
                st.session_state.target_currency = target_currency
                st.session_state.converted_col = f"Amount (in {target_currency})"

        # ===== Show results if already processed =====
        if "result_df" in st.session_state:
            result_df = st.session_state.result_df
            target_currency = st.session_state.target_currency
            converted_col = st.session_state.converted_col

            st.subheader("2️⃣ Processed Data")
            st.dataframe(result_df, use_container_width=True)

            # Metrics
            total_converted = result_df[converted_col].sum()
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Rows", len(result_df))
            col2.metric("Sum of original Amount", f"{result_df['Amount'].sum():,.2f}")
            col3.metric(f"Sum in {target_currency}", f"{total_converted:,.2f}")

            # Category Summary
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

            # ==============================
            # 3️⃣ Graph: Payments by Payee – Year & Period Filter + Select Payees
            # ==============================
            st.markdown("---")
            st.subheader("3️⃣ Payments by Payee – Year & Period Filter")

            # Prepare base data
            chart_df = result_df.copy()
            chart_df = chart_df.dropna(subset=["Payment Date", converted_col])
            chart_df["Year"] = chart_df["Payment Date"].dt.year
            chart_df["Month"] = chart_df["Payment Date"].dt.to_period("M").astype(str)
            chart_df["Quarter"] = chart_df["Payment Date"].dt.to_period("Q").astype(str)

            if chart_df.empty:
                st.warning("No valid dated transactions available for charting.")
            else:
                # ---------- Filters ----------
                available_years = sorted(chart_df["Year"].dropna().unique().astype(int).tolist())

                col_f1, col_f2, col_f3 = st.columns(3)

                with col_f1:
                    selected_years = st.multiselect(
                        "Select Year(s)",
                        options=available_years,
                        default=available_years,
                        help="Leave empty to show nothing"
                    )

                with col_f2:
                    period_type = st.selectbox(
                        "Period type",
                        options=["Monthly", "Quarterly"],
                        index=0
                    )

                with col_f3:
                    view_mode = st.selectbox(
                        "Show amounts",
                        options=["All amounts", "Payments only (negative)", "Receipts only (positive)"],
                        index=0
                    )

                # Apply year + sign filters first
                if not selected_years:
                    st.warning("Please select at least one year.")
                else:
                    filtered_df = chart_df[chart_df["Year"].isin(selected_years)].copy()

                    if view_mode == "Payments only (negative)":
                        filtered_df = filtered_df[filtered_df[converted_col] < 0]
                    elif view_mode == "Receipts only (positive)":
                        filtered_df = filtered_df[filtered_df[converted_col] > 0]

                    if filtered_df.empty:
                        st.warning("No data available for the selected filters.")
                    else:
                        # ----- Payee selection -----
                        # Sort payees by absolute total amount (largest first)
                        payee_totals = (
                            filtered_df.groupby("Party Name")[converted_col]
                            .apply(lambda x: x.abs().sum())
                            .sort_values(ascending=False)
                        )
                        all_payees = payee_totals.index.tolist()

                        st.markdown("#### Select Payees")
                        col_p1, col_p2 = st.columns([3, 1])

                        with col_p1:
                            selected_payees = st.multiselect(
                                "Choose payees to display (you can select / deselect freely)",
                                options=all_payees,
                                default=all_payees[:10],   # default top 10
                                help="Deselect any payee you don't want to see in the chart"
                            )

                        with col_p2:
                            st.write("")  # spacing
                            st.write("")
                            if st.button("Select All", use_container_width=True):
                                st.session_state.force_payees = all_payees
                                st.rerun()
                            if st.button("Clear All", use_container_width=True):
                                st.session_state.force_payees = []
                                st.rerun()

                        # Override selection if buttons were clicked
                        if "force_payees" in st.session_state:
                            selected_payees = st.session_state.force_payees
                            # Clear the force flag after using it once
                            del st.session_state.force_payees

                        if not selected_payees:
                            st.warning("Please select at least one payee.")
                        else:
                            chart_data = filtered_df[filtered_df["Party Name"].isin(selected_payees)]

                            # Period column
                            period_col = "Month" if period_type == "Monthly" else "Quarter"

                            # Aggregate
                            monthly = (
                                chart_data.groupby([period_col, "Party Name"], as_index=False)[converted_col]
                                .sum()
                            )

                            # Chart type
                            chart_type = st.radio(
                                "Chart type",
                                options=["Stacked Bar", "Grouped Bar", "Line"],
                                horizontal=True,
                                index=0
                            )

                            title = (
                                f"{period_type} Amount by Payee ({target_currency}) – "
                                f"Years: {', '.join(map(str, selected_years))} – "
                                f"{len(selected_payees)} payees"
                            )

                            if chart_type == "Stacked Bar":
                                fig = px.bar(
                                    monthly,
                                    x=period_col,
                                    y=converted_col,
                                    color="Party Name",
                                    title=title,
                                    barmode="stack",
                                    labels={converted_col: f"Amount ({target_currency})"},
                                    height=550
                                )
                            elif chart_type == "Grouped Bar":
                                fig = px.bar(
                                    monthly,
                                    x=period_col,
                                    y=converted_col,
                                    color="Party Name",
                                    title=title,
                                    barmode="group",
                                    labels={converted_col: f"Amount ({target_currency})"},
                                    height=550
                                )
                            else:
                                fig = px.line(
                                    monthly,
                                    x=period_col,
                                    y=converted_col,
                                    color="Party Name",
                                    title=title,
                                    markers=True,
                                    labels={converted_col: f"Amount ({target_currency})"},
                                    height=550
                                )

                            fig.update_layout(
                                xaxis_title=period_type,
                                yaxis_title=f"Amount ({target_currency})",
                                legend_title="Payee",
                                hovermode="x unified"
                            )
                            st.plotly_chart(fig, use_container_width=True)

                            # Data table
                            with st.expander("View period data table"):
                                pivot = monthly.pivot(
                                    index=period_col,
                                    columns="Party Name",
                                    values=converted_col
                                ).fillna(0)
                                st.dataframe(pivot.style.format("{:,.2f}"), use_container_width=True)

            # ==============================
            # 4️⃣ Download
            # ==============================
            st.markdown("---")
            st.subheader("4️⃣ Download Result")

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

    except ImportError:
        st.error(
            "Missing package **openpyxl** or **plotly**. "
            "Please make sure your requirements.txt contains:\n"
            "```\nstreamlit>=1.28.0\npandas>=2.0.0\nopenpyxl>=3.1.0\nplotly>=5.18.0\n```"
        )
    except Exception as e:
        st.error(f"Error reading file: {e}")
        st.exception(e)

else:
    st.info("👆 Please upload your cashflow Excel or CSV file to begin.")

st.markdown("---")
st.caption("""
**Notes**  
• Amount: **positive** = receipt / inflow, **negative** = payment / outflow  
• You can freely select / deselect any payees using the multi-select box  
• Use "Select All" or "Clear All" buttons for convenience  
• Graph supports Year filter + Monthly / Quarterly view  
• Exchange rates are approximate — update `RATES_TO_USD` for production accuracy  
""")
