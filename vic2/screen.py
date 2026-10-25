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

    def _area(self, x, cols):
        tcol = x >> 3
        twid = 0 if tcol >= 40 else min(cols, 40 - tcol)
        return tcol, twid, (tcol + twid) * 8 + 1

    def _rows(self, y, tcol, twid, c):
        trow, tyo = y >> 3, y & 7
        self.colour(trow, tcol, twid, c)
        if tyo and trow + 1 < 25:
            self.colour(trow + 1, tcol, twid, c)

    def glyphs(self, font, x, y, xlim, codes):
        """OR glyphs into the bitmap from pixel x, y; stops at the first glyph that does not
        end left of xlim. Returns True if clipped."""
        if y >> 3 >= 25:
            return bool(codes)
        for code in codes:
            code &= 0x7F
            adv = font.advance[code]
            if x + adv > xlim:
                return True
            for r, b in enumerate(font.glyphs[code]):
                for j in range(8):
                    if b & (0x80 >> j) and y + r < 200:
                        self.bits[y + r][x + j] = 1
            x += adv
        return False

    def text_line(self, font, x, y, cols, c, codes):
        """v2t_line; returns (clipped, next y)"""
        tcol, twid, xlim = self._area(x, cols)
        if y >> 3 < 25:
            for yy in range(y, min(200, y + 8)):
                for xx in range(tcol * 8, (tcol + twid) * 8):
                    self.bits[yy][xx] = 0
            self._rows(y, tcol, twid, c)
        return self.glyphs(font, x, y, xlim, codes), y + 8

    def v2t(self, font, data, x=None, y=None, lead=None):
        """v2t_draw (x, y, lead from the header) or v2t_draw_at, data = .v2t file contents"""
        assert data[:4] == b"V2T\x03"
        x = data[4] * 8 if x is None else x
        y = data[5] * 8 if y is None else y
        lead = data[9] if lead is None else lead
        tcol, twid, xlim = self._area(x, data[6])
        p = 10
        for _ in range(data[7]):
            c, n = data[p], data[p + 1]
            codes = data[p + 2:p + 2 + n]
            p += 2 + n
            if n:
                if y >> 3 < 25:
                    self._rows(y, tcol, twid, c)
                self.glyphs(font, x, y, xlim, codes)
            y += 8 + lead

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
