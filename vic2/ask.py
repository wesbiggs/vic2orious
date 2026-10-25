"""The "ask" demo: an image with questions the player picks with the number keys, each
answered with v2t_line while the image is displayed (asm/ask.s).

input/<name>.ask: an optional first line "# TITLE", then paragraphs (blank-line separated,
"# " paragraphs in the title colour) introducing the picture, then topics: a line
"> K label" (K = key, a digit 1-9) followed by the paragraphs of the answer.
"""

import os

from . import font as fonts

C_TITLE = (1 << 4) | 0        # white on black
C_BODY = (15 << 4) | 0        # light grey on black
C_HILITE = (7 << 4) | 0        # yellow on black: the topic being answered
C_FOOT = (11 << 4) | 0        # dark grey on black
STRESS = "The quick brown fox jumps over the lazy dog, again and again and again."


class NoRoom(SystemExit):
    pass


def parse(text):
    lines = text.strip("\n").splitlines()
    title = None
    if lines and lines[0].startswith("# "):
        title, lines = lines[0][2:].strip(), lines[1:]
    intro, topics, cur = [], [], None
    for line in lines:
        if line.startswith("> "):
            key, _, label = line[2:].strip().partition(" ")
            if len(key) != 1 or key not in "123456789" or any(k == int(key) for k, _, _ in topics):
                raise SystemExit("ask: bad or repeated topic key in %r" % line)
            cur = []
            topics.append((int(key), label.strip(), cur))
        else:
            (intro if cur is None else cur).append(line)
    if not topics:
        raise SystemExit("ask: no topics (lines starting with \"> \")")
    return title, "\n".join(intro), [(k, label, "\n".join(body)) for k, label, body in topics]


class Ask:
    def __init__(self, path, info, area, leading, log=print):
        from .build import text_layout
        with open(path) as f:
            self.title, intro, self.topics = parse(f.read())
        self.info = info
        self.col, row0, self.width, height = area
        self.leading = leading
        font = fonts.current()
        n = len(self.topics)
        lr = self.line_rows = -(-font.height // 8)     # character rows a line takes
        self.title_y = row0 * 8
        self.menu_row = row0 + (lr + 1 if self.title else 0)
        self.ans_row = self.menu_row + n * lr + 1
        self.foot_row = row0 + height - lr
        self.ans_rows = self.foot_row - 1 - self.ans_row
        if self.ans_rows < max(3, lr):
            raise NoRoom("ask %s: no room for answers in a %dx%d area" % (info["name"], self.width, height))
        keys = [k for k, _, _ in self.topics]
        self.labels = ["%d  %s" % (k, label) for k, label, _ in self.topics]
        self.foot = "%s: ask   SPACE: leave" % (
            "%d-%d" % (min(keys), max(keys)) if len(keys) > 1 else keys[0])
        self.answers = []
        for i, text in enumerate([intro] + [body for _, _, body in self.topics]):
            rows, lost = text_layout(text, font, self.width * 8, self.ans_rows * 8, leading)
            if lost:
                log("  ask %s: answer %d does not fit, %d line(s) dropped" % (info["name"], i, lost))
            self.answers.append(rows)
        for s in self.labels + [self.foot] + ([self.title] if self.title else []):
            if font.width(s) - font.hang > self.width * 8:
                log("  ask %s: %r is wider than the area and will be clipped" % (info["name"], s))
        log("  ask %s: %d topics, area %dx%d at column %d, row %d" %
            (info["name"], n, self.width, height, self.col, row0))

    @staticmethod
    def codes(s):
        return fonts.codes(s)

    def write_inc(self, path):
        def string(label, s):
            return "%s: .byte %s" % (label, ",".join("%d" % c for c in self.codes(s) + [0]))
        n = len(self.topics)
        out = ["ASK_N = %d" % n, "ASK_X = %d" % (self.col * 8), "ASK_COL = %d" % self.col,
               "ASK_W = %d" % self.width, "ASK_HAS_TITLE = %d" % bool(self.title),
               "ASK_TITLE_Y = %d" % self.title_y, "ASK_MENU_Y = %d" % (self.menu_row * 8),
               "ASK_ANS_ROW = %d" % self.ans_row, "ASK_ANS_ROWS = %d" % self.ans_rows,
               "ASK_ANS_Y = %d" % (self.ans_row * 8), "ASK_FOOT_Y = %d" % (self.foot_row * 8),
               "ASK_LEAD = %d" % self.leading,
               "ASK_MENU_LEAD = %d" % (self.line_rows * 8 - fonts.current().height),
               "ASK_LINE_ROWS = %d" % self.line_rows,
               "C_TITLE = $%02x" % C_TITLE, "C_BODY = $%02x" % C_BODY,
               "C_HILITE = $%02x" % C_HILITE, "C_FOOT = $%02x" % C_FOOT, "", "        .data",
               string("ask_title", self.title or ""), string("ask_foot", self.foot),
               string("ask_stress", STRESS),
               "ask_menu_row: .byte %s" % ",".join(
                   "%d" % (self.menu_row + i * self.line_rows) for i in range(n)),
               "ask_key: .byte %s" % ",".join("%d" % k for k, _, _ in self.topics),
               "ask_lbl_lo: .byte %s" % ",".join("<lbl%d" % i for i in range(n)),
               "ask_lbl_hi: .byte %s" % ",".join(">lbl%d" % i for i in range(n)),
               "ask_ans_lo: .byte %s" % ",".join("<ans%d" % i for i in range(n + 1)),
               "ask_ans_hi: .byte %s" % ",".join(">ans%d" % i for i in range(n + 1))]
        for i, s in enumerate(self.labels):
            out.append(string("lbl%d" % i, s))
        for i, rows in enumerate(self.answers):
            out.append("ans%d:" % i)
            for colour, line in rows:
                out.append("        .byte $%02x,%s" % (colour, ",".join("%d" % c for c in self.codes(line) + [0])))
            out.append("        .byte $ff")
        out.append('ask_img: .incbin "%s", 2' % self.info["v2i"])
        with open(path, "w") as f:
            f.write("\n".join(out) + "\n")

    def model(self, screen, font, sel):
        """What ask.s built with AUTO = sel + 1 leaves on the screen: title, menu with topic
        sel highlighted, its answer, and the stress line (black on black) at the bottom."""
        x = self.col * 8
        if self.title:
            screen.text_line(font, x, self.title_y, self.width, C_TITLE, self.codes(self.title))
        for i, label in enumerate(self.labels):
            screen.text_line(font, x, (self.menu_row + i * self.line_rows) * 8, self.width,
                             C_HILITE if i == sel else C_BODY, self.codes(label))
        screen.clear(self.col, self.ans_row, self.width, self.ans_rows, 0)
        y = self.ans_row * 8
        for colour, line in self.answers[sel + 1]:
            screen.text_line(font, x, y, self.width, colour, self.codes(line))
            y += font.height + self.leading
        screen.text_line(font, x, self.foot_row * 8, self.width, 0, self.codes(STRESS))
