# -*- coding: utf-8 -*-
"""Просмотр расписания дачных автобусов Оренбурга из dacha_schedule.json."""

import argparse
import json
import os
import sys
import tkinter as tk
import webbrowser

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILE = os.path.join(APP_DIR, "dacha_schedule.json")
NEWS_FILE = os.path.join(APP_DIR, "dacha_news.json")

BG = "#F4F7FB"
PANEL = "#FFFFFF"
BORDER = "#CBD8E6"
TEXT = "#2B3A4A"
MUTED = "#7A8796"
ACCENT = "#3E7CB1"
ACCENT_DARK = "#1F3A5F"
BUTTON_BG = "#E8EEF5"
BUTTON_HOVER = "#DCE7F4"
CHIP_BG = "#E2ECF8"
CHIP_FG = "#1F3A5F"
GROUP_BG = "#EDF3FA"
WARN = "#B35C2E"
GOOD = "#2E7D4F"

BASE_FONT = ("Segoe UI", 11)
BOLD_FONT = ("Segoe UI", 11, "bold")
SMALL_FONT = ("Segoe UI", 9)
TITLE_FONT = ("Segoe UI", 18, "bold")
CELL_FONT = ("Segoe UI", 12, "bold")

COLUMNS = 7


def load_schedule(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "routes" not in data:
        raise ValueError("Нет ключа 'routes' в файле")
    routes = data["routes"]
    routes.sort(key=_route_sort_key)
    return data, routes


def load_news(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        news = data.get("news") if isinstance(data, dict) else None
        if isinstance(news, dict) and (news.get("title") or news.get("text")):
            return news
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def _open_url(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _route_sort_key(route):
    num = str(route.get("number", ""))
    digits = "".join(ch for ch in num if ch.isdigit()) or "0"
    return int(digits), num


def _block_caption(block):
    parts = []
    if block.get("days"):
        parts.append("Дни: " + str(block["days"]))
    if block.get("valid_from"):
        parts.append("Действует с " + str(block["valid_from"]))
    if not parts:
        return "Расписание"
    return " \u00b7 ".join(parts)


class ScrollFrame(tk.Frame):
    def __init__(self, master, bg=BG):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.vsb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width)
        )

    def bind_wheel(self):
        handler = lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units")
        for widget in (self.canvas, self.inner):
            widget.bind("<MouseWheel>", handler, add="+")
        for child in self.inner.winfo_children():
            if isinstance(child, tk.Button):
                child.bind("<MouseWheel>", handler, add="+")


class RouteWindow(tk.Toplevel):
    def __init__(self, master, route):
        super().__init__(master)
        self.route = route
        self.configure(bg=BG)
        self.title(str(route.get("name", route.get("number", ""))))
        self.geometry("760x620")
        self.minsize(560, 400)

        header = tk.Frame(self, bg=PANEL)
        header.pack(fill="x", padx=14, pady=(14, 0))
        tk.Frame(header, bg=ACCENT, height=4).pack(fill="x")

        top = tk.Frame(header, bg=PANEL)
        top.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(
            top, text=str(route.get("number", "")), bg=PANEL, fg=ACCENT,
            font=("Segoe UI", 26, "bold"),
        ).pack(side="left", padx=(0, 12))
        tk.Label(
            top, text=str(route.get("name", "")), bg=PANEL, fg=TEXT,
            font=("Segoe UI", 16, "bold"), wraplength=620, justify="left",
        ).pack(side="left", fill="x", expand=True)

        meta = tk.Frame(header, bg=PANEL)
        meta.pack(fill="x", padx=16, pady=(0, 12))

        days_notes = route.get("days_notes") or []
        if days_notes:
            tk.Label(
                meta, text="Дни: " + "; ".join(str(d) for d in days_notes),
                bg=PANEL, fg=WARN, font=BOLD_FONT, anchor="w",
            ).pack(fill="x", pady=(0, 2))

        carrier = route.get("carrier")
        if carrier:
            tk.Label(
                meta, text=str(carrier), bg=PANEL, fg=TEXT,
                font=BASE_FONT, anchor="w",
            ).pack(fill="x", pady=(0, 2))

        tk.Label(
            meta, text="MD5 маршрута: " + str(route.get("md5", "")),
            bg=PANEL, fg=MUTED, font=SMALL_FONT, anchor="w",
        ).pack(fill="x")

        body = ScrollFrame(self)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        schedule = route.get("schedule") or []
        if not schedule:
            self._empty(body.inner, "Расписание отсутствует")
            return

        for block in schedule:
            group = tk.Frame(body.inner, bg=PANEL, highlightthickness=1,
                             highlightbackground=BORDER)
            group.pack(fill="x", pady=(0, 12))

            cap = tk.Frame(group, bg=GROUP_BG)
            cap.pack(fill="x")
            tk.Label(
                cap, text=_block_caption(block), bg=GROUP_BG, fg=ACCENT_DARK,
                font=BOLD_FONT, anchor="w", padx=12, pady=4,
            ).pack(fill="x")
            if block.get("note"):
                tk.Label(
                    cap, text="\u203A " + str(block["note"]), bg=GROUP_BG,
                    fg=WARN, font=("Segoe UI", 10, "italic"), anchor="w",
                    padx=12, pady=6, wraplength=640, justify="left",
                ).pack(fill="x")

            for stop in block.get("stops", []):
                stop_box = tk.Frame(group, bg=PANEL)
                stop_box.pack(fill="x", padx=12, pady=(8, 4))

                tk.Label(
                    stop_box, text=str(stop.get("point", "(не указан пункт)")),
                    bg=PANEL, fg=ACCENT_DARK, font=BOLD_FONT, anchor="w",
                ).pack(fill="x", pady=(0, 4))

                times = stop.get("times") or []
                row = tk.Frame(stop_box, bg=PANEL)
                row.pack(fill="x")
                for t in times:
                    chip = tk.Label(
                        row, text=str(t), bg=CHIP_BG, fg=CHIP_FG,
                        font=BOLD_FONT, padx=10, pady=3,
                    )
                    chip.pack(side="left", padx=(0, 6), pady=2)

            tk.Frame(group, bg=BORDER, height=1).pack(fill="x", pady=(6, 0))

        body.bind_wheel()
        for child in body.inner.winfo_children():
            if isinstance(child, tk.Frame):
                for lbl in child.winfo_children():
                    lbl.bind("<MouseWheel>",
                             lambda e: body.canvas.yview_scroll(int(-e.delta / 120), "units"),
                             add="+")
                    for sub in lbl.winfo_children():
                        sub.bind("<MouseWheel>",
                                 lambda e: body.canvas.yview_scroll(int(-e.delta / 120), "units"),
                                 add="+")

    def _empty(self, parent, text):
        tk.Label(parent, text=text, bg=BG, fg=MUTED, font=BASE_FONT).pack(padx=20, pady=24)


class NewsWindow(tk.Toplevel):
    def __init__(self, master, news):
        super().__init__(master)
        self.news = news
        self.configure(bg=BG)
        self.title("Последняя новость")
        self.geometry("720x520")
        self.minsize(520, 360)

        header = tk.Frame(self, bg=PANEL)
        header.pack(fill="x", padx=14, pady=(14, 0))
        tk.Frame(header, bg=ACCENT, height=4).pack(fill="x")

        top = tk.Frame(header, bg=PANEL)
        top.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(top, text="\uD83D\uDCF0", bg=PANEL, font=("Segoe UI", 26),
                 ).pack(side="left", padx=(0, 12))
        tk.Label(top, text=str(news.get("title", "")), bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 15, "bold"), wraplength=560, justify="left",
                 ).pack(side="left", fill="x", expand=True)

        meta = tk.Frame(header, bg=PANEL)
        meta.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(meta, text="Дата: " + str(news.get("date", "")), bg=PANEL,
                 fg=TEXT, font=BOLD_FONT, anchor="w").pack(fill="x", pady=(0, 2))
        url = str(news.get("url", ""))
        if url:
            link = tk.Label(meta, text=url, bg=PANEL, fg=ACCENT, font=SMALL_FONT,
                            anchor="w", cursor="hand2")
            link.pack(fill="x", pady=(0, 2))
            link.bind("<Button-1>", lambda e, u=url: _open_url(u))
        tk.Label(meta, text="ID: " + str(news.get("news_id", "")) + "  \u00b7  MD5: "
                 + str(news.get("md5", "")), bg=PANEL, fg=MUTED, font=SMALL_FONT,
                 anchor="w").pack(fill="x")

        body = ScrollFrame(self)
        body.pack(fill="both", expand=True, padx=14, pady=14)
        text_frame = tk.Frame(body.inner, bg=PANEL, highlightthickness=1,
                              highlightbackground=BORDER)
        text_frame.pack(fill="x", pady=(0, 12))
        self._text_lbl = tk.Label(text_frame, text=str(news.get("text", "")),
                                  bg=PANEL, fg=TEXT, font=BASE_FONT,
                                  justify="left", anchor="nw")
        self._text_lbl.pack(fill="x", padx=14, pady=14)
        text_frame.bind(
            "<Configure>",
            lambda e: self._text_lbl.configure(
                wraplength=max(200, e.width - 28)
            ),
        )
        body.bind_wheel()
        text_frame.bind(
            "<MouseWheel>",
            lambda e: body.canvas.yview_scroll(int(-e.delta / 120), "units"),
            add="+",
        )
        self._text_lbl.bind(
            "<MouseWheel>",
            lambda e: body.canvas.yview_scroll(int(-e.delta / 120), "units"),
            add="+",
        )


class App(tk.Tk):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.data = None
        self.routes = []
        self.search_var = tk.StringVar()
        self.button_map = {}
        self.news = None
        self.news_path = os.path.join(os.path.dirname(os.path.abspath(path)),
                                      "dacha_news.json")

        self.title("Расписание дачных маршрутов Оренбурга")
        self.configure(bg=BG)
        self.geometry("980x720")
        self.minsize(720, 520)

        self._build_header()
        self._build_toolbar()
        self._build_body()
        self._build_news()
        self._build_status()

        self.refresh()

    def _build_header(self):
        header = tk.Frame(self, bg=PANEL)
        header.pack(fill="x")
        tk.Frame(header, bg=ACCENT, height=4).pack(fill="x")
        row = tk.Frame(header, bg=PANEL)
        row.pack(fill="x", padx=18, pady=14)
        tk.Label(
            row, text="\uD83D\uDE8C  Расписание дачных маршрутов",
            bg=PANEL, fg=ACCENT_DARK, font=TITLE_FONT,
        ).pack(side="left")
        tk.Button(
            row, text="Обновить", command=self.refresh, bg=ACCENT, fg="white",
            activebackground=ACCENT_DARK, activeforeground="white",
            font=BOLD_FONT, relief="flat", padx=16, pady=6, cursor="hand2",
        ).pack(side="right")

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=18, pady=(12, 8))
        tk.Label(bar, text="Поиск:", bg=BG, fg=TEXT, font=BOLD_FONT).pack(side="left")
        entry = tk.Entry(
            bar, textvariable=self.search_var, bg=PANEL, fg=TEXT,
            font=BASE_FONT, relief="solid", bd=1, highlightthickness=0,
        )
        entry.pack(side="left", fill="x", expand=True, padx=(8, 16), ipady=4)
        self.search_var.trace_add("write", lambda *a: self.render_grid())

    def _build_body(self):
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.empty_label = tk.Label(
            self.scroll.inner, text="", bg=BG, fg=MUTED, font=BASE_FONT,
            justify="left", anchor="n",
        )
        self.empty_label.pack(padx=4, pady=16, fill="x")

    def _build_news(self):
        self.news_wrapper = tk.Frame(self, bg=BG)
        self.news_wrapper.pack(fill="x", side="bottom", padx=18, pady=(0, 10))

    def _build_status(self):
        self.status = tk.Label(
            self, text="", bg="#E9EFF6", fg=MUTED, font=SMALL_FONT,
            anchor="w", padx=18, pady=6,
        )
        self.status.pack(fill="x", side="bottom")

    def refresh(self):
        try:
            self.data, self.routes = load_schedule(self.path)
        except FileNotFoundError:
            self.routes = []
            self._show_status(f"Файл не найден: {self.path}", WARN)
        except ValueError as exc:
            self.routes = []
            self._show_status(f"Ошибка в файле: {exc}", WARN)
        except json.JSONDecodeError as exc:
            self.routes = []
            self._show_status(f"Файл повреждён (JSON): {exc}", WARN)
        self.news = load_news(self.news_path)
        self.render_grid()
        self._render_news()

    def _render_news(self):
        for w in self.news_wrapper.winfo_children():
            w.destroy()
        news = self.news
        if not news:
            return
        card = tk.Frame(self.news_wrapper, bg=BUTTON_BG, cursor="hand2")
        card.pack(fill="x")
        head = tk.Frame(card, bg=BUTTON_BG)
        head.pack(fill="x", padx=14, pady=(8, 0))
        title_lbl = tk.Label(
            head, text="\uD83D\uDCF0  " + str(news.get("title", "Новость")),
            bg=BUTTON_BG, fg=ACCENT_DARK, font=BOLD_FONT, anchor="w",
            cursor="hand2",
        )
        title_lbl.pack(side="left")
        date = str(news.get("date", ""))
        date_lbl = None
        if date:
            date_lbl = tk.Label(head, text=date, bg=BUTTON_BG, fg=MUTED,
                                font=SMALL_FONT, cursor="hand2")
            date_lbl.pack(side="right")
        text_lbl = tk.Label(
            card, text=str(news.get("text", "")), bg=BUTTON_BG, fg=TEXT,
            font=BASE_FONT, justify="left", anchor="w", cursor="hand2",
        )
        text_lbl.pack(fill="x", padx=14, pady=(4, 8))
        card.bind(
            "<Configure>",
            lambda e: text_lbl.configure(wraplength=max(180, e.width - 28)),
        )
        for w in (card, head, title_lbl, text_lbl):
            w.bind("<Button-1>", lambda e: self.open_news())
        if date_lbl is not None:
            date_lbl.bind("<Button-1>", lambda e: self.open_news())

    def open_news(self):
        if self.news:
            NewsWindow(self, self.news)

    def filtered_routes(self):
        q = self.search_var.get().strip().lower()
        if not q:
            return self.routes
        return [r for r in self.routes
                if q in str(r.get("number", "")).lower()
                or q in str(r.get("name", "")).lower()]

    def render_grid(self):
        for w in self.scroll.inner.winfo_children():
            w.destroy()
        routes = self.filtered_routes()

        if not routes:
            if self.routes:
                self.empty_label = tk.Label(
                    self.scroll.inner, text="Ничего не найдено по запросу.",
                    bg=BG, fg=MUTED, font=BASE_FONT,
                )
            else:
                self.empty_label = tk.Label(
                    self.scroll.inner,
                    text="Данные не загружены.\n\nФайл: {}\n\n"
                         "Положите dacha_schedule.json рядом с программой\n"
                         "или запустите python schedule_viewer.py <путь_к_файлу>".format(self.path),
                    bg=BG, fg=MUTED, font=BASE_FONT, justify="center",
                )
            self.empty_label.pack(padx=8, pady=24)
            self.scroll.bind_wheel()
            self._update_count()
            return

        for i, route in enumerate(routes):
            btn = tk.Button(
                self.scroll.inner, text=str(route.get("number", "?")),
                font=CELL_FONT, bg=BUTTON_BG, fg=ACCENT_DARK,
                activebackground=ACCENT, activeforeground="white",
                relief="flat", cursor="hand2", padx=6, pady=10,
                command=lambda r=route: self.open_route(r),
            )
            btn.grid(row=i // COLUMNS, column=i % COLUMNS,
                     sticky="nsew", padx=3, pady=3)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=BUTTON_HOVER))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=BUTTON_BG))
            self.button_map[id(btn)] = btn

        for col in range(COLUMNS):
            self.scroll.inner.grid_columnconfigure(col, weight=1, uniform="cell")

        self.scroll.bind_wheel()
        self._update_count()

    def _update_count(self):
        shown = len(self.filtered_routes())
        total = len(self.routes)
        if total:
            self._show_status(
                f"Маршрутов: {shown} из {total} \u00b7 Файл: {self.path}", TEXT
            )

    def _show_status(self, text, fg):
        self.status.configure(text=text, fg=fg)

    def open_route(self, route):
        RouteWindow(self, route)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", default=DEFAULT_FILE,
                        help="путь к dacha_schedule.json")
    args = parser.parse_args(argv)
    app = App(os.path.abspath(args.file))
    app.mainloop()


if __name__ == "__main__":
    main(sys.argv[1:])