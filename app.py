            # ==============================
            # 3️⃣ Graph: Payments by Payee each Month / Period
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

                col_f1, col_f2, col_f3, col_f4 = st.columns(4)

                with col_f1:
                    selected_years = st.multiselect(
                        "Select Year(s)",
                        options=available_years,
                        default=available_years,          # all years by default
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

                with col_f4:
                    top_n = st.slider("Top N payees", min_value=5, max_value=30, value=10)

                # Apply year filter
                if not selected_years:
                    st.warning("Please select at least one year.")
                else:
                    chart_df = chart_df[chart_df["Year"].isin(selected_years)]

                    # Apply sign filter
                    if view_mode == "Payments only (negative)":
                        chart_df = chart_df[chart_df[converted_col] < 0]
                    elif view_mode == "Receipts only (positive)":
                        chart_df = chart_df[chart_df[converted_col] > 0]

                    if chart_df.empty:
                        st.warning("No data available for the selected filters.")
                    else:
                        # Period column
                        if period_type == "Monthly":
                            period_col = "Month"
                        else:
                            period_col = "Quarter"

                        # Top N payees by absolute amount
                        payee_totals = (
                            chart_df.groupby("Party Name")[converted_col]
                            .apply(lambda x: x.abs().sum())
                            .sort_values(ascending=False)
                        )
                        top_payees = payee_totals.head(top_n).index.tolist()
                        chart_df = chart_df[chart_df["Party Name"].isin(top_payees)]

                        # Aggregate
                        monthly = (
                            chart_df.groupby([period_col, "Party Name"], as_index=False)[converted_col]
                            .sum()
                        )

                        # Chart type selector
                        chart_type = st.radio(
                            "Chart type",
                            options=["Stacked Bar", "Grouped Bar", "Line"],
                            horizontal=True,
                            index=0
                        )

                        # Build chart
                        title = f"{period_type} Amount by Payee ({target_currency}) – Years: {', '.join(map(str, selected_years))} – Top {top_n}"

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
