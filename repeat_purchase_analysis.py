"""
Customer Repeat Purchase Analysis
Task 28 - Data Analytics Track, Veda Technology

Measures repeat purchase behaviour and identifies repeat-customer segments.

Outputs (written to --output-dir):
    customer_metrics.csv     customer_id, total_orders, customer_type
    customer_segments.csv    customer-level orders / value / AOV / segment
    segment_summary.csv      one row per segment (the "segment table")
    aov_comparison.csv       AOV: one-time vs repeat customers, first vs repeat orders
    monthly_repeat_rate.csv  share of active customers each month who had bought before
    cohort_retention.csv     cohort retention (% of a cohort active in month N)
    repeat_purchase_analysis.png

Usage:
    python repeat_purchase_analysis.py --data data.csv --output-dir .

Supported column names (first match wins):
    customer : CustomerID | customer_unique_id | customer_id
    order    : InvoiceNo | order_id
    date     : InvoiceDate | order_purchase_timestamp | order_date
    value    : Quantity * UnitPrice | order_value | price   (summed per order)
For Olist, join orders + customers + order_items into one file first, so that
customer_unique_id, order_id, order_purchase_timestamp and price are present.
"""

import argparse
import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

warnings.filterwarnings("ignore")

CUSTOMER_COLS = ["CustomerID", "customer_unique_id", "customer_id"]
ORDER_COLS = ["InvoiceNo", "order_id"]
DATE_COLS = ["InvoiceDate", "order_purchase_timestamp", "order_date"]
SEGMENT_ORDER = ["VIP", "Loyal", "Occasional Repeat", "One-time"]


def first_present(columns, candidates, label):
    for col in candidates:
        if col in columns:
            return col
    raise ValueError(f"No {label} column found. Expected one of {candidates}")


class RepeatPurchaseAnalyzer:
    """Analyzes customer repeat purchase behaviour at the ORDER level."""

    def __init__(self, data_path, output_dir="."):
        self.data_path = data_path
        self.output_dir = output_dir
        self.raw = None
        self.orders = None            # one row per order
        self.customer_metrics = None
        self.segments = None
        self.segment_summary = None
        self.aov_by_type = None
        self.aov_by_sequence = None
        self.monthly = None
        self.cohorts = None
        self.vip_threshold = None
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------ load
    def load_data(self):
        print("Loading data...")
        self.raw = pd.read_csv(self.data_path)
        print(f"Data loaded. Shape: {self.raw.shape}")
        print(f"Columns: {list(self.raw.columns)}")
        return self.raw

    # ------------------------------------------------------------ preprocess
    def preprocess_data(self):
        """Clean line-level data and aggregate to ONE ROW PER ORDER."""
        print("\nPreprocessing data...")
        df = self.raw.copy()
        cols = df.columns

        cust = first_present(cols, CUSTOMER_COLS, "customer")
        order = first_present(cols, ORDER_COLS, "order")
        date = first_present(cols, DATE_COLS, "date")

        # Order value = Quantity * UnitPrice per line (the bug in the old script
        # was using UnitPrice alone and ignoring Quantity).
        if "Quantity" in cols and "UnitPrice" in cols:
            df["line_value"] = df["Quantity"] * df["UnitPrice"]
            df = df[(df["Quantity"] > 0) & (df["UnitPrice"] > 0)]   # drop returns / bad rows
        elif "order_value" in cols:
            df["line_value"] = df["order_value"]
        elif "price" in cols:
            df["line_value"] = df["price"]
        else:
            raise ValueError("Cannot derive order value: need Quantity+UnitPrice, order_value or price")

        df = df.dropna(subset=[cust, order, date])
        df["order_date"] = pd.to_datetime(df[date])

        # Aggregate line items -> orders, so AOV is per ORDER, not per row.
        self.orders = (
            df.groupby([cust, order], as_index=False)
              .agg(order_date=("order_date", "min"), order_value=("line_value", "sum"))
              .rename(columns={cust: "customer_id", order: "order_id"})
        )
        self.orders["order_month"] = self.orders["order_date"].dt.strftime("%Y-%m")
        print(f"Orders after cleaning: {len(self.orders)} "
              f"from {self.orders['customer_id'].nunique()} customers")
        return self.orders

    # ------------------------------------------------------ repeat customers
    def define_repeat_customers(self, min_orders=2):
        """Repeat customer = placed at least `min_orders` distinct orders."""
        print(f"\nDefining repeat customers (>= {min_orders} orders)...")
        cm = (self.orders.groupby("customer_id")["order_id"].nunique()
              .rename("total_orders").reset_index())
        cm["customer_type"] = cm["total_orders"].apply(
            lambda x: "Repeat" if x >= min_orders else "One-time")
        self.customer_metrics = cm
        counts = cm["customer_type"].value_counts()
        print(f"Total customers: {len(cm)}")
        print(f"Repeat customers: {counts.get('Repeat', 0)}")
        print(f"One-time customers: {counts.get('One-time', 0)}")
        return cm

    def calculate_repeat_rate(self, verbose=True):
        if self.customer_metrics is None:
            self.define_repeat_customers()
        repeat = (self.customer_metrics["customer_type"] == "Repeat").sum()
        rate = repeat / len(self.customer_metrics) * 100
        if verbose:
            print(f"\nRepeat rate: {rate:.2f}% ({repeat} of {len(self.customer_metrics)} customers)")
        return rate

    # ------------------------------------------------------------------- AOV
    def calculate_aov_comparison(self, verbose=True):
        """AOV two ways: by customer type, and first order vs repeat orders."""
        o = self.orders.merge(self.customer_metrics[["customer_id", "customer_type"]],
                              on="customer_id")
        self.aov_by_type = (o.groupby("customer_type")["order_value"]
                            .agg(customers=lambda s: o.loc[s.index, "customer_id"].nunique(),
                                 orders="count", total_value="sum", aov="mean")
                            .round(2).reset_index())

        o = o.sort_values(["customer_id", "order_date", "order_id"])
        o["order_number"] = o.groupby("customer_id").cumcount() + 1
        o["order_type"] = o["order_number"].apply(
            lambda n: "First order" if n == 1 else "Repeat order")
        self.aov_by_sequence = (o.groupby("order_type")["order_value"]
                                .agg(orders="count", total_value="sum", aov="mean")
                                .round(2).reset_index())
        if verbose:
            print("\nAOV: one-time vs repeat customers")
            print(self.aov_by_type.to_string(index=False))
            print("\nAOV: first orders vs repeat orders")
            print(self.aov_by_sequence.to_string(index=False))
        return self.aov_by_type, self.aov_by_sequence

    # -------------------------------------------------------------- segments
    def create_segments(self):
        """
        Mutually exclusive segments:
          VIP               5+ orders AND total spend above the 75th percentile
          Loyal             5+ orders
          Occasional Repeat 2-4 orders
          One-time          1 order
        """
        print("\nCreating customer segments...")
        cs = (self.orders.groupby("customer_id")
              .agg(total_orders=("order_id", "nunique"),
                   total_value=("order_value", "sum"),
                   avg_order_value=("order_value", "mean"),
                   std_order_value=("order_value", "std"))
              .reset_index())
        self.vip_threshold = cs["total_value"].quantile(0.75)

        def label(r):
            if r.total_orders >= 5 and r.total_value > self.vip_threshold:
                return "VIP"
            if r.total_orders >= 5:
                return "Loyal"
            if r.total_orders >= 2:
                return "Occasional Repeat"
            return "One-time"

        cs["segment"] = cs.apply(label, axis=1)
        self.segments = cs

        total_rev = cs["total_value"].sum()
        summ = (cs.groupby("segment")
                .agg(customers=("customer_id", "count"),
                     total_orders=("total_orders", "sum"),
                     total_value=("total_value", "sum"))
                .reindex(SEGMENT_ORDER).reset_index())
        summ["pct_customers"] = (summ["customers"] / len(cs) * 100).round(1)
        summ["pct_revenue"] = (summ["total_value"] / total_rev * 100).round(1)
        summ["avg_orders_per_customer"] = (summ["total_orders"] / summ["customers"]).round(2)
        summ["aov"] = (summ["total_value"] / summ["total_orders"]).round(2)
        summ["total_value"] = summ["total_value"].round(2)
        self.segment_summary = summ

        print(f"VIP spend threshold (75th percentile): {self.vip_threshold:.2f}")
        print(summ.to_string(index=False))
        return cs

    # ----------------------------------------------------- time-based views
    def calculate_monthly_repeat_rate(self):
        """Per month: share of active customers who had ordered in an EARLIER month."""
        first = self.orders.groupby("customer_id")["order_month"].min().rename("first_month")
        m = (self.orders.groupby(["order_month", "customer_id"]).size()
             .reset_index(name="orders_in_month").merge(first, on="customer_id"))
        m["returning"] = m["first_month"] < m["order_month"]
        out = (m.groupby("order_month")
               .agg(active_customers=("customer_id", "count"),
                    returning_customers=("returning", "sum"))
               .reset_index())
        out["returning_rate"] = (out["returning_customers"] / out["active_customers"] * 100).round(2)
        self.monthly = out
        return out

    def calculate_cohort_retention(self):
        first = self.orders.groupby("customer_id")["order_month"].min().rename("cohort_month")
        o = self.orders.merge(first, on="customer_id")
        a = (o.groupby(["cohort_month", "order_month"])["customer_id"].nunique()
             .reset_index(name="active_customers"))
        size = first.value_counts().rename("cohort_customers").rename_axis("cohort_month").reset_index()
        a = a.merge(size, on="cohort_month")
        cy, cm = a["cohort_month"].str[:4].astype(int), a["cohort_month"].str[5:7].astype(int)
        ay, am = a["order_month"].str[:4].astype(int), a["order_month"].str[5:7].astype(int)
        a["month_number"] = (ay - cy) * 12 + (am - cm) + 1
        a["retention_pct"] = (a["active_customers"] / a["cohort_customers"] * 100).round(2)
        self.cohorts = a.rename(columns={"order_month": "activity_month"}) \
                        .sort_values(["cohort_month", "activity_month"]).reset_index(drop=True)
        return self.cohorts

    # -------------------------------------------------------------- insights
    def generate_insights(self):
        print("\n" + "=" * 50)
        print("KEY INSIGHTS")
        print("=" * 50)

        rate = self.calculate_repeat_rate(verbose=False)
        n = len(self.customer_metrics)
        rep = (self.customer_metrics["customer_type"] == "Repeat").sum()
        print(f"\n1. Repeat rate: {rate:.2f}% ({rep} of {n} customers ordered 2+ times)")
        if rate > 80:
            print("   - Unusually high for retail (typically well below 50%). Check whether the")
            print("     dataset is synthetic or limited to already-engaged customers.")
        elif rate > 30:
            print("   - Healthy loyalty; protect it with retention programmes.")
        elif rate > 15:
            print("   - Moderate loyalty; room to improve retention.")
        else:
            print("   - Low repeat rate; retention is a priority.")

        t = self.aov_by_type.set_index("customer_type")["aov"]
        s = self.aov_by_sequence.set_index("order_type")["aov"]
        print("\n2. AOV comparison")
        print(f"   - Repeat customers: {t['Repeat']:.2f}  |  One-time customers: {t['One-time']:.2f}")
        diff = (t["Repeat"] - t["One-time"]) / t["One-time"] * 100
        print(f"   - Repeat customers' orders are {abs(diff):.1f}% "
              f"{'larger' if diff > 0 else 'smaller'} than one-time customers' orders")
        print(f"   - First orders: {s['First order']:.2f}  |  Later (repeat) orders: {s['Repeat order']:.2f}")

        print("\n3. Segments")
        for _, r in self.segment_summary.iterrows():
            print(f"   - {r['segment']}: {int(r['customers'])} customers "
                  f"({r['pct_customers']}%), {r['pct_revenue']}% of revenue")

        full = self.monthly[self.monthly["order_month"] != self.monthly["order_month"].max()]
        print(f"\n4. Average monthly returning-customer share (excl. first and partial months): "
              f"{full['returning_rate'].iloc[1:].mean():.1f}%")

        print("\n" + "=" * 50)
        print("RECOMMENDATIONS")
        print("=" * 50)
        print("1. Build a VIP/loyalty tier: VIP customers generate a disproportionate share of revenue")
        print("2. Win-back campaign for the one-time customers")
        print("3. Nudge 'Occasional Repeat' customers (2-4 orders) towards their 5th order")
        print("4. Track first-order AOV vs repeat-order AOV to test upsell offers")

    # --------------------------------------------------------- visualisation
    def create_visualizations(self):
        print("\nCreating visualizations...")
        fig, ax = plt.subplots(2, 3, figsize=(18, 10))

        counts = self.customer_metrics["customer_type"].value_counts()
        ax[0, 0].pie(counts.values, labels=counts.index, autopct="%1.1f%%")
        ax[0, 0].set_title("Customer Type Distribution")

        ax[0, 1].hist(self.customer_metrics["total_orders"],
                      bins=range(1, int(self.customer_metrics["total_orders"].max()) + 2),
                      edgecolor="black", align="left")
        ax[0, 1].set(xlabel="Orders per customer", ylabel="Customers",
                     title="Distribution of Orders per Customer")

        sns.barplot(x="customers", y="segment", data=self.segment_summary, ax=ax[0, 2],
                    order=SEGMENT_ORDER)
        ax[0, 2].set(xlabel="Customers", ylabel="", title="Customer Segments")

        sns.barplot(data=self.aov_by_type, x="customer_type", y="aov", ax=ax[1, 0])
        ax[1, 0].set(xlabel="", ylabel="Average order value",
                     title="AOV: One-time vs Repeat Customers")

        sns.barplot(data=self.aov_by_sequence, x="order_type", y="aov", ax=ax[1, 1])
        ax[1, 1].set(xlabel="", ylabel="Average order value",
                     title="AOV: First Order vs Repeat Orders")

        ax[1, 2].plot(self.monthly["order_month"], self.monthly["returning_rate"], marker="o")
        ax[1, 2].set(ylabel="% of active customers", title="Monthly Returning-Customer Share")
        ax[1, 2].tick_params(axis="x", rotation=60)
        ax[1, 2].text(0.01, 0.02, "Last month is a partial month", transform=ax[1, 2].transAxes,
                      fontsize=8, color="gray")

        plt.tight_layout()
        path = os.path.join(self.output_dir, "repeat_purchase_analysis.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Visualization saved to {path}")

    # ------------------------------------------------------------------ save
    def save_results(self):
        print("\nSaving results...")
        files = {
            "customer_metrics.csv": self.customer_metrics,
            "customer_segments.csv": self.segments,
            "segment_summary.csv": self.segment_summary,
            "monthly_repeat_rate.csv": self.monthly,
            "cohort_retention.csv": self.cohorts,
        }
        for name, frame in files.items():
            frame.to_csv(os.path.join(self.output_dir, name), index=False)
            print(f"  saved {name}")
        aov = pd.concat([
            self.aov_by_type.rename(columns={"customer_type": "group"}).assign(comparison="By customer type"),
            self.aov_by_sequence.rename(columns={"order_type": "group"}).assign(comparison="By order sequence"),
        ])
        aov.to_csv(os.path.join(self.output_dir, "aov_comparison.csv"), index=False)
        print("  saved aov_comparison.csv")

    # ------------------------------------------------------------------- run
    def run_analysis(self):
        print("=" * 50)
        print("CUSTOMER REPEAT PURCHASE ANALYSIS")
        print("=" * 50)
        self.load_data()
        self.preprocess_data()
        self.define_repeat_customers(min_orders=2)
        self.calculate_repeat_rate()
        self.calculate_aov_comparison()
        self.create_segments()
        self.calculate_monthly_repeat_rate()
        self.calculate_cohort_retention()
        self.generate_insights()
        self.create_visualizations()
        self.save_results()
        print("\nAnalysis completed successfully!")


def main():
    parser = argparse.ArgumentParser(description="Customer repeat purchase analysis")
    parser.add_argument("--data", default="data.csv", help="path to the dataset CSV")
    parser.add_argument("--output-dir", default=".", help="where to write results")
    args = parser.parse_args()
    try:
        RepeatPurchaseAnalyzer(args.data, args.output_dir).run_analysis()
    except FileNotFoundError:
        print(f"Error: data file '{args.data}' not found. Save your dataset as data.csv "
              "or pass --data <path>.")


if __name__ == "__main__":
    main()
