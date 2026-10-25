"""Python model of the hires screen as v2t.inc's text and clear routines leave it, for
--verify: bitmap bits plus cell colours, with images pasted on top."""


class Screen:
    def __init__(self):
        self.bits = [[0] * 320 for _ in range(200)]
        self.cells = [[0] * 40 for _ in range(25)]          # fg << 4 | bg
        self.over = {}                                      # (x, y) -> colour of pasted images

    def colour(self, row, col, cols, c):
        if row < 25:
            for x in range(col, min(40, col + cols)):
                self.cells[row][x] = c

    def clear(self, col, row, cols, rows, c):
        """v2t_clear"""
        for r in range(row, min(25, row + rows)):
            for y in range(r * 8, r * 8 + 8):
                for x in range(col * 8, min(40, col + cols) * 8):
                    self.bits[y][x] = 0
            self.colour(r, col, cols, c)

    def _area(self, font, x, cols):
        tcol = x >> 3
        twid = 0 if tcol >= 40 else min(cols, 40 - tcol)
        return tcol, twid, (tcol + twid) * 8 + font.hang

    def _rows(self, font, y, tcol, twid, c):
        for row in range(y >> 3, min(25, ((y + font.height - 1) >> 3) + 1)):
            self.colour(row, tcol, twid, c)

    def glyphs(self, font, x, y, xlim, codes):
        """OR glyphs into the bitmap from pixel x, y; stops at the first glyph that does not
        end left of xlim. Returns True if clipped."""
        if y >> 3 >= 25:
            return bool(codes)
        for code in codes:
            o, w = font.glyph(code)
            if x + w > xlim:
                return True
            for r in range(min(font.height, 200 - y)):
                for j in range(w):
                    if font.bit(r, o + j):
                        self.bits[y + r][x + j] = 1
            x += w
        return False

    def text_line(self, font, x, y, cols, c, codes):
        """v2t_line; returns (clipped, next y)"""
        tcol, twid, xlim = self._area(font, x, cols)
        if y >> 3 < 25:
            for yy in range(y, min(200, y + font.height)):
                for xx in range(tcol * 8, (tcol + twid) * 8):
                    self.bits[yy][xx] = 0
            self._rows(font, y, tcol, twid, c)
        return self.glyphs(font, x, y, xlim, codes), y + font.height

    def v2t(self, font, data, x=None, y=None, lead=None):
        """v2t_draw (x, y, lead from the header) or v2t_draw_at, data = .v2t file contents"""
        assert data[:4] == b"V2T\x04" and data[8] == font.height
        x = data[4] * 8 if x is None else x
        y = data[5] * 8 if y is None else y
        lead = data[9] if lead is None else lead
        tcol, twid, xlim = self._area(font, x, data[6])
        p = 10
        for _ in range(data[7]):
            c, n = data[p], data[p + 1]
            codes = data[p + 2:p + 2 + n]
            p += 2 + n
            if n:
                if y >> 3 < 25:
                    self._rows(font, y, tcol, twid, c)
                self.glyphs(font, x, y, xlim, codes)
            y += font.height + lead

    def paste(self, img, x0, y0):
        for y, row in enumerate(img):
            for x, v in enumerate(row):
                self.over[(x0 + x, y0 + y)] = v

    def pixels(self):
        out = []
        for y in range(200):
            row = []
            for x in range(320):
                v = self.over.get((x, y))
                if v is None:
                    c = self.cells[y >> 3][x >> 3]
                    v = c >> 4 if self.bits[y][x] else c & 15
                row.append(v)
            out.append(row)
        return out
