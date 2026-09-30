"""天氣圖表與統計視覺化模組.

使用 Plotly 建立現代化、互動式氣溫折線圖、溫差帶狀圖與地區比較長條圖。
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import pandas as pd
import plotly.graph_objects as go


def create_temperature_line_chart(
    df: pd.DataFrame,
    region_name: str = "選定地區",
) -> go.Figure:
    """建立指定地區之一週最低溫 (MinT) 與最高溫 (MaxT) 互動折線圖.

    包含氣溫區間填充色彩與懸浮資訊。
    """
    fig = go.Figure()

    if df.empty:
        fig.add_annotation(
            text="暫無氣溫預報資料",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=18, color="gray"),
        )
        return fig

    # 依日期排序
    df_sorted = df.sort_values(by="dataDate").copy()

    # 最低溫線 (底層)
    fig.add_trace(
        go.Scatter(
            x=df_sorted["dataDate"],
            y=df_sorted["minT"],
            mode="lines+markers+text",
            name="最低氣溫 (MinT)",
            text=df_sorted["minT"].apply(lambda v: f"{v:.0f}°" if pd.notnull(v) else ""),
            textposition="bottom center",
            line=dict(color="#1f77b4", width=3),
            marker=dict(size=9, symbol="circle", color="#1f77b4"),
            hovertemplate="<b>日期</b>: %{x}<br><b>最低溫</b>: %{y:.1f}°C<extra></extra>",
        )
    )

    # 最高溫線 (頂層，填充區間到最低溫)
    fig.add_trace(
        go.Scatter(
            x=df_sorted["dataDate"],
            y=df_sorted["maxT"],
            mode="lines+markers+text",
            name="最高氣溫 (MaxT)",
            text=df_sorted["maxT"].apply(lambda v: f"{v:.0f}°" if pd.notnull(v) else ""),
            textposition="top center",
            line=dict(color="#ff4b4b", width=3),
            marker=dict(size=9, symbol="circle", color="#ff4b4b"),
            fill="tonexty",
            fillcolor="rgba(255, 75, 75, 0.12)",
            hovertemplate="<b>日期</b>: %{x}<br><b>最高溫</b>: %{y:.1f}°C<extra></extra>",
        )
    )

    # 樣式與排版設定
    fig.update_layout(
        title=dict(
            text=f"📈 {region_name} - 一週最高與最低氣溫趨勢",
            font=dict(size=18, family="sans-serif"),
        ),
        xaxis=dict(
            title="預報日期",
            type="category",
            gridcolor="rgba(200, 200, 200, 0.2)",
            showgrid=True,
        ),
        yaxis=dict(
            title="氣溫 (°C)",
            ticksuffix="°C",
            gridcolor="rgba(200, 200, 200, 0.2)",
            showgrid=True,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        hovermode="x unified",
        margin=dict(l=40, r=40, t=60, b=40),
        template="plotly_white",
        height=420,
    )

    return fig


def create_region_comparison_chart(
    df: pd.DataFrame,
    selected_date: str,
) -> go.Figure:
    """建立指定日期全台各地區最高與最低氣溫比較長條圖."""
    fig = go.Figure()

    if df.empty:
        fig.add_annotation(
            text=f"在 {selected_date} 尚無任何地區資料",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color="gray"),
        )
        return fig

    df_filtered = df[df["dataDate"] == selected_date].sort_values(by="regionName")

    if df_filtered.empty:
        fig.add_annotation(
            text=f"在 {selected_date} 尚無任何地區資料",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color="gray"),
        )
        return fig

    fig.add_trace(
        go.Bar(
            name="最低氣溫 (MinT)",
            x=df_filtered["regionName"],
            y=df_filtered["minT"],
            marker_color="#1f77b4",
            text=df_filtered["minT"].apply(lambda v: f"{v:.1f}°C" if pd.notnull(v) else ""),
            textposition="auto",
        )
    )

    fig.add_trace(
        go.Bar(
            name="最高氣溫 (MaxT)",
            x=df_filtered["regionName"],
            y=df_filtered["maxT"],
            marker_color="#ff4b4b",
            text=df_filtered["maxT"].apply(lambda v: f"{v:.1f}°C" if pd.notnull(v) else ""),
            textposition="auto",
        )
    )

    fig.update_layout(
        title=dict(
            text=f"📊 {selected_date} 全台各地區氣溫對比",
            font=dict(size=18),
        ),
        barmode="group",
        xaxis=dict(title="地區"),
        yaxis=dict(title="氣溫 (°C)", ticksuffix="°C"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_white",
        margin=dict(l=40, r=40, t=60, b=40),
        height=380,
    )

    return fig


def calculate_temperature_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """計算資料集中氣溫的關鍵統計摘要指標."""
    if df.empty:
        return {
            "avg_min": None,
            "avg_max": None,
            "peak_max": None,
            "lowest_min": None,
            "max_diff": None,
            "count": 0,
        }

    valid_min = df["minT"].dropna()
    valid_max = df["maxT"].dropna()

    avg_min = valid_min.mean() if not valid_min.empty else None
    avg_max = valid_max.mean() if not valid_max.empty else None
    lowest_min = valid_min.min() if not valid_min.empty else None
    peak_max = valid_max.max() if not valid_max.empty else None

    # 計算每日溫差
    diff_series = (df["maxT"] - df["minT"]).dropna()
    max_diff = diff_series.max() if not diff_series.empty else None

    return {
        "avg_min": avg_min,
        "avg_max": avg_max,
        "peak_max": peak_max,
        "lowest_min": lowest_min,
        "max_diff": max_diff,
        "count": len(df),
    }
