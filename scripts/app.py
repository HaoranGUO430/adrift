"""Alert board: show the alert events of the stream pipeline in a window"""

import time
import tkinter as tk
from collections.abc import Callable, Iterator
from pathlib import Path
from tkinter import ttk

import duckdb
import pandas as pd
from stream_simulation import SPEED, incident_period

ROOT = Path(__file__).resolve().parents[1]
VESSELS = ROOT / "clean_data" / "vessels.parquet"
GROUND_TRUTH = ROOT / "ground_truth" / "ground_truth.csv"

FONT = "Segoe UI"
BACKGROUND = "#f3f4f6"
CARD = "#ffffff"
ENDED_CARD = "#e5e7eb"
INK = "#111827"  # vessel names
MUTED = "#6b7280"  # details
LEVEL_COLOURS = {"Low": "#d4a000", "Mid": "#e86f00", "High": "#c81e1e"}
NAMES = dict(
    duckdb.sql(
        f"SELECT mmsi, name FROM read_parquet('{VESSELS.as_posix()}')"
    ).fetchall()
)


def incident_labels(incidents) -> dict[str, int]:
    """Drop-down labels of the tows to replay."""
    rows = duckdb.sql(f"""
        SELECT incident_num, tower_name, towed_name
        FROM read_csv('{GROUND_TRUTH.as_posix()}')
        WHERE incident_num IN {tuple(incidents)}
    """).fetchall()
    names = {num: f"{tower} -> {towed}" for num, tower, towed in rows}
    return {
        f"#{num}  {names[num]}  ({incident_period(num)[0]:%Y-%m-%d})": num
        for num in incidents
    }


def vessel_name(mmsi) -> str:
    """Registered name of a vessel, or its MMSI if it has no name."""
    return NAMES.get(mmsi) or f"MMSI {mmsi}"


class AlertBoard:
    """Window with the stream time and one column of alert cards per level."""

    def __init__(self, root, run, incidents) -> None:
        self.root = root
        self.run = run
        self.incidents = incident_labels(incidents)
        self.alerts = {}  # (tower, towed, start) -> {"level", "end"}: one entry per alert
        self.open = {}  # (tower, towed) -> key of its alert that has not ended yet
        self.stream = None
        self.next_tick = None
        self.label = ""  # e.g. "#23"
        self.paused = False
        root.title("adrift alert board")
        root.geometry("1280x720")
        root.configure(bg=BACKGROUND)

        top = tk.Frame(root, bg=BACKGROUND, padx=20, pady=16)
        top.pack(fill="x")
        self.choice = ttk.Combobox(
            top,
            values=list(self.incidents),
            state="readonly",
            width=55,
            font=(FONT, 11),
        )
        self.choice.current(0)
        self.choice.pack(side="left")
        ttk.Button(top, text="Start", command=self.start).pack(side="left", padx=10)
        self.pause_button = ttk.Button(
            top, text="Pause", command=self.pause, state="disabled"
        )
        self.pause_button.pack(side="left")

        clock = tk.Frame(root, bg=BACKGROUND, padx=20)
        clock.pack(fill="x")
        self.clock = tk.Label(
            clock, text="--:--", bg=BACKGROUND, fg=INK, font=(FONT, 26, "bold")
        )
        self.clock.pack(side="left")
        self.status = tk.Label(
            clock,
            text="choose a tow and press Start",
            bg=BACKGROUND,
            fg=MUTED,
            font=(FONT, 12),
        )
        self.status.pack(side="left", padx=14, pady=(10, 0))

        board = tk.Frame(root, bg=BACKGROUND, padx=14, pady=14)
        board.pack(fill="both", expand=True)
        self.headers, self.columns = {}, {}
        for column, (level, colour) in enumerate(LEVEL_COLOURS.items()):
            self.headers[level] = tk.Label(
                board, bg=colour, fg="white", font=(FONT, 15, "bold"), pady=6
            )
            self.headers[level].grid(row=0, column=column, sticky="ew", padx=6)
            self.columns[level] = tk.Frame(board, bg=BACKGROUND)
            self.columns[level].grid(
                row=1, column=column, sticky="nsew", padx=6, pady=(8, 0)
            )
            board.columnconfigure(column, weight=1, uniform="level")
        board.rowconfigure(1, weight=1)
        self.draw()

    def start(self) -> None:
        """Start replaying the chosen tow from the beginning."""
        if self.next_tick:
            self.root.after_cancel(self.next_tick)
        self.alerts = {}
        self.open = {}
        self.paused = False
        self.pause_button.config(text="Pause", state="normal")
        self.label = self.choice.get().split("  ")[0]
        self.stream = self.run(
            self.incidents[self.choice.get()], speed=None
        )  # the window sets the pace
        self.draw()
        self.tick()

    def tick(self) -> None:
        """Process one stream minute, show it, and plan the next one."""
        started = time.monotonic()
        try:
            now, events = next(self.stream)
        except StopIteration:
            self.status.config(text=f"{self.label}   replay finished")
            self.pause_button.config(state="disabled")
            return
        for event in events:
            self.apply(event)
        if events:
            self.draw()
        self.clock.config(text=f"{now:%Y-%m-%d  %H:%M} UTC")
        self.status.config(text=f"{self.label}   replaying")
        wait_ms = max(1, int((1 / SPEED - (time.monotonic() - started)) * 1000))
        self.next_tick = self.root.after(wait_ms, self.tick)

    def pause(self) -> None:
        """Pause the replay, or resume it where it stopped."""
        self.paused = not self.paused
        if self.paused:
            self.root.after_cancel(self.next_tick)
            self.pause_button.config(text="Resume")
            self.status.config(text=f"{self.label}   paused")
        else:
            self.pause_button.config(text="Pause")
            self.tick()

    def apply(self, event) -> None:
        """Apply one alert event from stream_alerts.update()."""
        minute, tower, towed, kind = event
        at = f"{pd.Timestamp(minute, unit='s'):%H:%M}"
        pair = (tower, towed)
        if kind == "Low":
            self.open[pair] = (tower, towed, at)
            self.alerts[self.open[pair]] = {"level": "Low", "end": None}
        elif kind in ("Mid", "High"):
            self.alerts[self.open[pair]]["level"] = kind
        else:
            key = self.open.pop(pair)
            if self.alerts[key]["level"] == "High":
                self.alerts[key]["end"] = at  # High alerts stay after the tow has ended
            else:
                del self.alerts[
                    key
                ]  # Low and Mid alerts disappear once the tow has ended

    def draw(self) -> None:
        """Redraw the three columns of alert cards."""
        for level, column in self.columns.items():
            for widget in column.winfo_children():
                widget.destroy()
            alerts = [
                (key, alert)
                for key, alert in self.alerts.items()
                if alert["level"] == level
            ]
            self.headers[level].config(text=f"{level.upper()}   {len(alerts)}")
            if not alerts:
                tk.Label(
                    column, text="no alert", bg=BACKGROUND, fg=MUTED, font=(FONT, 12)
                ).pack(pady=20)
            for (tower, towed, start), alert in alerts:
                self.card(column, tower, towed, start, alert)

    def card(self, column, tower, towed, start, alert) -> None:
        """Draw one alert: tower and towed names in large type, details below."""
        background = ENDED_CARD if alert["end"] else CARD
        card = tk.Frame(column, bg=background)
        card.pack(fill="x", pady=6)
        tk.Frame(card, bg=LEVEL_COLOURS[alert["level"]], width=8).pack(
            side="left", fill="y"
        )
        body = tk.Frame(card, bg=background, padx=14, pady=10)
        body.pack(side="left", fill="both", expand=True)

        def line(text, size, colour, bold=False) -> None:
            """One line of text on the card."""
            font = (FONT, size, "bold") if bold else (FONT, size)
            tk.Label(
                body,
                text=text,
                bg=background,
                fg=colour,
                font=font,
                anchor="w",
                justify="left",
                wraplength=340,
            ).pack(fill="x")

        line(vessel_name(tower), 17, INK, bold=True)
        line("is towing", 10, MUTED)
        line(vessel_name(towed), 17, INK, bold=True)
        line(f"MMSI {tower}  ->  {towed}", 9, MUTED)
        if alert["end"]:
            line(f"since {start}     ended {alert['end']}", 11, MUTED)
        else:
            line(f"since {start}", 11, INK, bold=True)


def show_board(run, incidents) -> None:
    """Open the alert board."""
    root = tk.Tk()
    AlertBoard(root, run, incidents)
    root.mainloop()
