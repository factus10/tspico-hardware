#!/usr/bin/env python3
"""Hand-finish helpers for the leftovers Freerouting will not do:
 - drop a via to the GND/+3V3 plane next to a pad or track end (`via` items)
 - route a signal between two points on the +3V3 plane layer In2.Cu, where the
   zone fill flows around it (`in2` items). Never on In1.Cu (GND).
Run with KiCad's Python. Edits tspico-v2.6.kicad_pcb in place, refills zones.
"""
import heapq, math, sys
import pcbnew

MM = pcbnew.FromMM
T = pcbnew.ToMM
CLR = 0.127
VIA_D, VIA_DRILL = 0.6, 0.3
TW = 0.2                      # signal track width on In2
EDGE = 0.35

def _in_area(z, x, y, rad):
    """True if a disc of radius rad at (x, y) touches rule area z."""
    o = z.Outline()
    if o.Contains(pcbnew.VECTOR2I(MM(x), MM(y))): return True
    return any(o.Contains(pcbnew.VECTOR2I(MM(x + rad * math.cos(k * math.pi / 4)), MM(y + rad * math.sin(k * math.pi / 4)))) for k in range(8))


def seg_dist(ax, ay, bx, by, px, py):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

class Board:
    def __init__(self, path, board=None):
        self.path = path
        self.b = board if board is not None else pcbnew.LoadBoard(path)
        bb = self.b.GetBoardEdgesBoundingBox()
        self.x0, self.y0, self.x1, self.y1 = T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())
        self.refresh()

    def refresh(self):
        b = self.b
        self.pads = []      # (x0, y0, x1, y1, net, through)
        for f in b.GetFootprints():
            for p in f.Pads():
                if not (p.GetLayerSet().Contains(pcbnew.F_Cu) or p.GetLayerSet().Contains(pcbnew.B_Cu)):
                    continue                      # paste-only sub-pads (the QFN's exposed-pad paste pattern) are not copper
                bb = p.GetBoundingBox()
                self.pads.append((T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom()),
                                  p.GetNetCode(), p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD))
        self.vias, self.tracks = [], []   # vias: (x,y,r,net); tracks: (ax,ay,bx,by,w/2,net,layer)
        for t in b.GetTracks():
            if t.GetClass() == "PCB_VIA":
                self.vias.append((T(t.GetPosition().x), T(t.GetPosition().y), T(t.GetWidth(pcbnew.F_Cu)) / 2, t.GetNetCode()))
            else:
                self.tracks.append((T(t.GetStart().x), T(t.GetStart().y), T(t.GetEnd().x), T(t.GetEnd().y), T(t.GetWidth()) / 2, t.GetNetCode(), t.GetLayer()))
        self.rule_areas = [z for z in b.Zones() if z.GetIsRuleArea()]

    @staticmethod
    def rect_dist(x0, y0, x1, y1, px, py):
        dx = max(x0 - px, 0, px - x1); dy = max(y0 - py, 0, py - y1)
        return math.hypot(dx, dy)

    def via_ok(self, x, y, net, d=VIA_D):
        r = max(d / 2 + CLR, (0.25 if d < 0.6 else VIA_DRILL) / 2 + 0.26)     # copper clearance and hole-to-copper clearance
        if x - self.x0 < EDGE + d / 2 or self.x1 - x < EDGE + d / 2 or y - self.y0 < EDGE + d / 2 or self.y1 - y < EDGE + d / 2:
            return False
        for x0, y0, x1, y1, pn, th in self.pads:
            if pn != net and self.rect_dist(x0, y0, x1, y1, x, y) < r:
                return False
        for vx, vy, vr, vn in self.vias:
            if math.hypot(vx - x, vy - y) < (r + vr if vn != net else d / 2 + vr + 0.05):
                return False
        for ax, ay, bx, by, hw, tn, _ in self.tracks:
            if tn != net and seg_dist(ax, ay, bx, by, x, y) < r + hw:
                return False
        for z in self.rule_areas:
            if z.GetDoNotAllowVias():
                for k in range(8):
                    a = k * math.pi / 4
                    if z.Outline().Contains(pcbnew.VECTOR2I(MM(x + r * math.cos(a)), MM(y + r * math.sin(a)))):
                        return False
        return True

    def track_ok(self, ax, ay, bx, by, net, layer, w=TW):
        """Segment clear of other-net copper on `layer` (pads sampled along the segment)."""
        r = w / 2 + CLR
        n = max(2, int(math.hypot(bx - ax, by - ay) / 0.05) + 1)
        pts = [(ax + (bx - ax) * i / (n - 1), ay + (by - ay) * i / (n - 1)) for i in range(n)]
        for x0, y0, x1, y1, pn, th in self.pads:
            if pn != net and (th or layer in (pcbnew.F_Cu,)) and any(self.rect_dist(x0, y0, x1, y1, px, py) < r for px, py in pts):
                return False
        for vx, vy, vr, vn in self.vias:
            if vn != net and seg_dist(ax, ay, bx, by, vx, vy) < r + vr:
                return False
        for tx0, ty0, tx1, ty1, hw, tn, tl in self.tracks:
            if tn != net and tl == layer and any(seg_dist(tx0, ty0, tx1, ty1, px, py) < r + hw for px, py in pts):
                return False
        for z in self.rule_areas:
            if z.GetDoNotAllowTracks() and z.GetLayerSet().Contains(layer) and any(_in_area(z, px, py, w / 2 + 0.02) for px, py in pts):
                return False
        return True

    def find_via_spot(self, x, y, net, rmax=1.6, dirs=None, w=TW):
        """Nearest clear via spot to (x,y) whose F.Cu stub from (x,y) is also
        clear; spirals outward, 0.6 via first then 0.5. `dirs` restricts the
        search to those unit directions (e.g. straight out of a pad)."""
        full = (self.pads, self.vias, self.tracks)
        R = rmax + 1.5
        self.pads = [p for p in full[0] if self.rect_dist(p[0], p[1], p[2], p[3], x, y) < R]
        self.vias = [v for v in full[1] if math.hypot(v[0] - x, v[1] - y) < R]
        self.tracks = [t for t in full[2] if seg_dist(t[0], t[1], t[2], t[3], x, y) < R]
        try:
            return self._find_via_spot(x, y, net, rmax, dirs, w)
        finally:
            self.pads, self.vias, self.tracks = full

    def _find_via_spot(self, x, y, net, rmax, dirs, w):
        for d in (0.6, 0.5):
            for k in range(0, int(rmax / 0.1) + 1):
                rr = k * 0.1
                cands = [(x, y)] if k == 0 else ([(x + rr * ux, y + rr * uy) for ux, uy in dirs] if dirs else
                                                 [(x + rr * math.cos(2 * math.pi * i / 16), y + rr * math.sin(2 * math.pi * i / 16)) for i in range(16)])
                for cx, cy in cands:
                    if self.via_ok(cx, cy, net, d) and (k == 0 or self.track_ok(x, y, cx, cy, net, pcbnew.F_Cu, w)):
                        return (cx, cy, d)
        return None

    lock = False        # set True to lock everything added (pre-routes the autorouter must keep)

    def add_via(self, x, y, net, d=VIA_D):
        v = pcbnew.PCB_VIA(self.b)
        v.SetLocked(self.lock)
        v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y))); v.SetDrill(MM(0.25 if d < 0.6 else VIA_DRILL)); v.SetWidth(MM(d))
        v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNetCode(net)
        self.b.Add(v)
        self.vias.append((x, y, d / 2, net))

    def add_track(self, ax, ay, bx, by, net, layer, w=TW):
        t = pcbnew.PCB_TRACK(self.b)
        t.SetLocked(self.lock)
        t.SetStart(pcbnew.VECTOR2I(MM(ax), MM(ay))); t.SetEnd(pcbnew.VECTOR2I(MM(bx), MM(by)))
        t.SetWidth(MM(w)); t.SetLayer(layer); t.SetNetCode(net)
        self.b.Add(t)
        self.tracks.append((ax, ay, bx, by, w / 2, net, layer))

    def stub_via(self, x, y, net, from_pad=True, rmax=1.6, dirs=None):
        """Via at or next to (x,y) joined by an F.Cu stub. Returns via spot."""
        w = 0.2
        spot = self.find_via_spot(x, y, net, rmax, dirs, w)
        if spot is None:
            return None
        if math.hypot(spot[0] - x, spot[1] - y) > 0.01:
            self.add_track(x, y, spot[0], spot[1], net, pcbnew.F_Cu, w)
        self.add_via(spot[0], spot[1], net, spot[2])
        return spot[:2]

    def polyline(self, pts, net, layer=pcbnew.F_Cu, w=TW):
        """Add a polyline if every segment is clear; returns True/False."""
        if not all(self.track_ok(a[0], a[1], b_[0], b_[1], net, layer, w) for a, b_ in zip(pts, pts[1:])):
            return False
        for a, b_ in zip(pts, pts[1:]):
            self.add_track(a[0], a[1], b_[0], b_[1], net, layer, w)
        return True

    # ---- In2 routing ------------------------------------------------------
    def in2_route(self, a, b, net, step=0.2, avoid=()):
        """avoid: list of (x0,y0,x1,y1,cost) rectangles the path is discouraged from crossing."""
        r = TW / 2 + CLR
        obst = []
        for x0, y0, x1, y1, pn, th in self.pads:
            if th and pn != net: obst.append(((x0 + x1) / 2, (y0 + y1) / 2, math.hypot(x1 - x0, y1 - y0) / 2 + r))
        for vx, vy, vr, vn in self.vias:
            if vn != net: obst.append((vx, vy, vr + r))
        segs = [(ax, ay, bx, by, hw + r) for ax, ay, bx, by, hw, tn, l in self.tracks if l == pcbnew.In2_Cu and tn != net]
        gx0, gy0 = self.x0 + EDGE + 0.3, self.y0 + EDGE + 0.3
        nx, ny = int((self.x1 - self.x0 - 2 * (EDGE + 0.3)) / step), int((self.y1 - self.y0 - 2 * (EDGE + 0.3)) / step)
        blocked = set()
        for ox, oy, orad in obst:
            R = orad + step
            for i in range(int((ox - R - gx0) / step), int((ox + R - gx0) / step) + 2):
                for j in range(int((oy - R - gy0) / step), int((oy + R - gy0) / step) + 2):
                    if 0 <= i < nx and 0 <= j < ny and math.hypot(gx0 + i * step - ox, gy0 + j * step - oy) < orad + step * 0.71:
                        blocked.add((i, j))
        for ax, ay, bx, by, srad in segs:
            R = srad + step
            for i in range(int((min(ax, bx) - R - gx0) / step), int((max(ax, bx) + R - gx0) / step) + 2):
                for j in range(int((min(ay, by) - R - gy0) / step), int((max(ay, by) + R - gy0) / step) + 2):
                    if 0 <= i < nx and 0 <= j < ny and seg_dist(ax, ay, bx, by, gx0 + i * step, gy0 + j * step) < srad + step * 0.71:
                        blocked.add((i, j))
        def cell(p): return (round((p[0] - gx0) / step), round((p[1] - gy0) / step))
        s, g = cell(a), cell(b)
        blocked.discard(s); blocked.discard(g)
        moves = [(1,0,1),(-1,0,1),(0,1,1),(0,-1,1),(1,1,1.414),(1,-1,1.414),(-1,1,1.414),(-1,-1,1.414)]
        openq = [(0, s)]; came = {s: None}; cost = {s: 0}
        while openq:
            _, c = heapq.heappop(openq)
            if c == g: break
            for dx, dy, w in moves:
                n = (c[0] + dx, c[1] + dy)
                if not (0 <= n[0] < nx and 0 <= n[1] < ny) or n in blocked: continue
                # no corner cutting through blocked cells
                if dx and dy and ((c[0] + dx, c[1]) in blocked or (c[0], c[1] + dy) in blocked): continue
                nc = cost[c] + w + (0.3 if came[c] is not None and (n[0]-c[0], n[1]-c[1]) != (c[0]-came[c][0], c[1]-came[c][1]) else 0)
                px_, py_ = gx0 + n[0] * step, gy0 + n[1] * step
                for ax0, ay0, ax1, ay1, ac in avoid:
                    if ax0 <= px_ <= ax1 and ay0 <= py_ <= ay1: nc += ac
                if nc < cost.get(n, 1e9):
                    cost[n] = nc; came[n] = c
                    heapq.heappush(openq, (nc + math.hypot(g[0]-n[0], g[1]-n[1]), n))
        if g not in came:
            return None
        path = []
        c = g
        while c is not None:
            path.append(c); c = came[c]
        path.reverse()
        # merge collinear runs
        pts = [path[0]]
        for i in range(1, len(path) - 1):
            d1 = (path[i][0]-path[i-1][0], path[i][1]-path[i-1][1]); d2 = (path[i+1][0]-path[i][0], path[i+1][1]-path[i][1])
            if d1 != d2: pts.append(path[i])
        pts.append(path[-1])
        mm = [(gx0 + i * step, gy0 + j * step) for i, j in pts]
        mm[0], mm[-1] = a, b
        for p, q in zip(mm, mm[1:]):
            self.add_track(p[0], p[1], q[0], q[1], net, pcbnew.In2_Cu)
        return mm

    def remove_near(self, x, y, net, r=0.3):
        """Remove tracks/vias of `net` with an end within r of (x,y); returns removed count."""
        gone = []
        for t in list(self.b.GetTracks()):
            if t.GetNetCode() != net: continue
            pts = [t.GetPosition()] if t.GetClass() == "PCB_VIA" else [t.GetStart(), t.GetEnd()]
            if any(math.hypot(T(p.x) - x, T(p.y) - y) < r for p in pts):
                gone.append(t)
        for t in gone: self.b.Remove(t)
        self.refresh()
        return len(gone)

    def layer_route(self, a, b, net, layer, margin=3.0, step=0.1, w=TW):
        """A* on one copper layer inside the bounding box of a and b (+margin):
        obstacles are other-net pads on that layer, vias, and same-layer tracks."""
        r = w / 2 + CLR
        # grid aligned to the start point, so a 0.4 mm pitch pad lane stays on the grid
        x0 = a[0] - math.ceil((a[0] - (min(a[0], b[0]) - margin)) / step) * step
        y0 = a[1] - math.ceil((a[1] - (min(a[1], b[1]) - margin)) / step) * step
        x1, y1 = max(a[0], b[0]) + margin, max(a[1], b[1]) + margin
        nx, ny = int((x1 - x0) / step) + 2, int((y1 - y0) / step) + 2
        blocked = set()
        def block_circle(ox, oy, orad):
            R = orad + step
            for i in range(max(0, int((ox - R - x0) / step)), min(nx, int((ox + R - x0) / step) + 2)):
                for j in range(max(0, int((oy - R - y0) / step)), min(ny, int((oy + R - y0) / step) + 2)):
                    if math.hypot(x0 + i * step - ox, y0 + j * step - oy) < orad + step * 0.71: blocked.add((i, j))
        def block_seg(ax, ay, bx, by, srad):
            R = srad + step
            for i in range(max(0, int((min(ax, bx) - R - x0) / step)), min(nx, int((max(ax, bx) + R - x0) / step) + 2)):
                for j in range(max(0, int((min(ay, by) - R - y0) / step)), min(ny, int((max(ay, by) + R - y0) / step) + 2)):
                    if seg_dist(ax, ay, bx, by, x0 + i * step, y0 + j * step) < srad + step * 0.71: blocked.add((i, j))
        for px0, py0, px1, py1, pn, th in self.pads:
            if pn == net or not (th or layer == pcbnew.F_Cu): continue
            if px1 < x0 or px0 > x1 or py1 < y0 or py0 > y1: continue
            for i in range(max(0, int((px0 - r - x0) / step)), min(nx, int((px1 + r - x0) / step) + 2)):
                for j in range(max(0, int((py0 - r - y0) / step)), min(ny, int((py1 + r - y0) / step) + 2)):
                    if self.rect_dist(px0, py0, px1, py1, x0 + i * step, y0 + j * step) < r + step * 0.71: blocked.add((i, j))
        for vx, vy, vr, vn in self.vias:
            if vn != net and x0 <= vx <= x1 and y0 <= vy <= y1: block_circle(vx, vy, vr + r)
        for ax, ay, bx, by, hw, tn, l in self.tracks:
            if l == layer and tn != net and not (max(ax, bx) < x0 or min(ax, bx) > x1 or max(ay, by) < y0 or min(ay, by) > y1): block_seg(ax, ay, bx, by, hw + r)
        for z in self.rule_areas:
            if z.GetDoNotAllowTracks() and z.GetLayerSet().Contains(layer):
                bb = z.GetBoundingBox()
                for i in range(max(0, int((T(bb.GetLeft()) - r - x0) / step)), min(nx, int((T(bb.GetRight()) + r - x0) / step) + 2)):
                    for j in range(max(0, int((T(bb.GetTop()) - r - y0) / step)), min(ny, int((T(bb.GetBottom()) + r - y0) / step) + 2)):
                        if z.Outline().Contains(pcbnew.VECTOR2I(MM(x0 + i * step), MM(y0 + j * step))): blocked.add((i, j))
        def cell(p): return (round((p[0] - x0) / step), round((p[1] - y0) / step))
        s, g = cell(a), cell(b)
        blocked.discard(s); blocked.discard(g)
        moves = [(1,0,1),(-1,0,1),(0,1,1),(0,-1,1),(1,1,1.414),(1,-1,1.414),(-1,1,1.414),(-1,-1,1.414)]
        openq = [(0, s)]; came = {s: None}; cost = {s: 0}
        while openq:
            _, c = heapq.heappop(openq)
            if c == g: break
            for dx, dy, wt in moves:
                n = (c[0] + dx, c[1] + dy)
                if not (0 <= n[0] < nx and 0 <= n[1] < ny) or n in blocked: continue
                if dx and dy and ((c[0] + dx, c[1]) in blocked or (c[0], c[1] + dy) in blocked): continue
                nc = cost[c] + wt + (0.5 if came[c] is not None and (n[0]-c[0], n[1]-c[1]) != (c[0]-came[c][0], c[1]-came[c][1]) else 0)
                if nc < cost.get(n, 1e9):
                    cost[n] = nc; came[n] = c
                    heapq.heappush(openq, (nc + math.hypot(g[0]-n[0], g[1]-n[1]), n))
        if g not in came: return None
        path = []; c = g
        while c is not None: path.append(c); c = came[c]
        path.reverse()
        pts = [path[0]]
        for i in range(1, len(path) - 1):
            d1 = (path[i][0]-path[i-1][0], path[i][1]-path[i-1][1]); d2 = (path[i+1][0]-path[i][0], path[i+1][1]-path[i][1])
            if d1 != d2: pts.append(path[i])
        pts.append(path[-1])
        mm = [(x0 + i * step, y0 + j * step) for i, j in pts]
        mm[0], mm[-1] = a, b
        if not all(self.track_ok(p[0], p[1], q[0], q[1], net, layer, w) for p, q in zip(mm, mm[1:])):
            return None
        for p, q in zip(mm, mm[1:]): self.add_track(p[0], p[1], q[0], q[1], net, layer, w)
        return mm

    def save(self):
        pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())
        pcbnew.SaveBoard(self.path, self.b)


def why_not(B, x, y, net, d=VIA_D):
    """List the items blocking a via of diameter d at (x, y)."""
    r = d / 2 + CLR
    out = []
    for x0, y0, x1, y1, pn, th in B.pads:
        dd = B.rect_dist(x0, y0, x1, y1, x, y)
        if pn != net and dd < r: out.append(("pad", B.b.FindNet(pn).GetNetname(), round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2), round(dd, 3)))
    for vx, vy, vr, vn in B.vias:
        dd = math.hypot(vx - x, vy - y)
        if dd < r + vr: out.append(("via", B.b.FindNet(vn).GetNetname(), round(vx, 2), round(vy, 2), round(dd, 3)))
    for ax, ay, bx, by, hw, tn, l in B.tracks:
        dd = seg_dist(ax, ay, bx, by, x, y)
        if tn != net and dd < r + hw: out.append(("trk", B.b.FindNet(tn).GetNetname(), pcbnew.LayerName(l), round(ax, 2), round(ay, 2), round(bx, 2), round(by, 2), round(dd, 3)))
    for z in B.rule_areas:
        if z.GetDoNotAllowVias() and any(z.Outline().Contains(pcbnew.VECTOR2I(MM(x + r * math.cos(k * math.pi / 4)), MM(y + r * math.sin(k * math.pi / 4)))) for k in range(8)):
            out.append(("keepout", z.GetZoneName()))
    return out


def why_track(B, ax, ay, bx, by, net, layer=pcbnew.F_Cu, w=TW):
    r = w / 2 + CLR
    n = max(2, int(math.hypot(bx - ax, by - ay) / 0.05) + 1)
    pts = [(ax + (bx - ax) * i / (n - 1), ay + (by - ay) * i / (n - 1)) for i in range(n)]
    out = []
    for x0, y0, x1, y1, pn, th in B.pads:
        if pn != net and (th or layer == pcbnew.F_Cu):
            dd = min(B.rect_dist(x0, y0, x1, y1, px, py) for px, py in pts)
            if dd < r: out.append(("pad", B.b.FindNet(pn).GetNetname(), round((x0+x1)/2, 2), round((y0+y1)/2, 2), round(dd, 3)))
    for vx, vy, vr, vn in B.vias:
        dd = seg_dist(ax, ay, bx, by, vx, vy)
        if vn != net and dd < r + vr: out.append(("via", B.b.FindNet(vn).GetNetname(), round(vx, 2), round(vy, 2), round(dd, 3)))
    for tx0, ty0, tx1, ty1, hw, tn, tl in B.tracks:
        if tn != net and tl == layer:
            dd = min(seg_dist(tx0, ty0, tx1, ty1, px, py) for px, py in pts)
            if dd < r + hw: out.append(("trk", B.b.FindNet(tn).GetNetname(), round(tx0, 2), round(ty0, 2), round(tx1, 2), round(ty1, 2), round(dd, 3)))
    return out


def islands(B, netname):
    """Union-find over the net's pads, tracks and vias by geometric contact.
    Returns a list of islands, each a dict with its items and dead-end points."""
    b = B.b
    net = b.GetNetcodeFromNetname(netname)
    items = []
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() == net:
                bb = p.GetBoundingBox()
                items.append(("pad", f.GetReference() + ":" + p.GetNumber(), (T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())),
                              None if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD else pcbnew.F_Cu))
    for t in b.GetTracks():
        if t.GetNetCode() != net: continue
        if t.GetClass() == "PCB_VIA":
            items.append(("via", (T(t.GetPosition().x), T(t.GetPosition().y)), None, None))
        else:
            items.append(("trk", (T(t.GetStart().x), T(t.GetStart().y)), (T(t.GetEnd().x), T(t.GetEnd().y)), t.GetLayer()))
    par = list(range(len(items)))
    def find(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    def union(i, j): par[find(i)] = find(j)
    def touches_pt(it, x, y, layer):
        k = it[0]
        if k == "via": return math.hypot(it[1][0] - x, it[1][1] - y) < 0.02
        if k == "pad": return (it[3] is None or layer is None or it[3] == layer) and B.rect_dist(*it[2], x, y) < 0.02
        if k == "trk": return (layer is None or it[3] == layer) and (math.hypot(it[1][0]-x, it[1][1]-y) < 0.02 or math.hypot(it[2][0]-x, it[2][1]-y) < 0.02 or seg_dist(it[1][0], it[1][1], it[2][0], it[2][1], x, y) < 0.02)
    for i, it in enumerate(items):
        if it[0] == "trk":
            for x, y in (it[1], it[2]):
                for j, jt in enumerate(items):
                    if j != i and touches_pt(jt, x, y, it[3]): union(i, j)
        elif it[0] == "via":
            for j, jt in enumerate(items):
                if j != i and touches_pt(jt, it[1][0], it[1][1], None): union(i, j)
    groups = {}
    for i in range(len(items)): groups.setdefault(find(i), []).append(items[i])
    out = []
    for g in groups.values():
        pads = [it[1] for it in g if it[0] == "pad"]
        vias = [it[1] for it in g if it[0] == "via"]
        # dead ends: track endpoints touched by nothing else in the group
        ends = []
        for it in g:
            if it[0] != "trk": continue
            for x, y in (it[1], it[2]):
                if not any(jt is not it and touches_pt(jt, x, y, it[3]) for jt in g): ends.append((round(x, 2), round(y, 2), pcbnew.LayerName(it[3])))
        out.append({"pads": pads, "vias": len(vias), "tracks": sum(1 for it in g if it[0] == "trk"), "ends": ends})
    return out


def escape(B, p, net, radius=3.5, tries=80):
    """From a point on F.Cu (a pad or a track end), find the nearest legal via
    spot that an F.Cu path can actually reach, add the path and the via."""
    for vx, vy, vr, vn in B.vias:
        if vn == net and math.hypot(vx - p[0], vy - p[1]) < 0.06:
            return (vx, vy)
    cands = []
    n = int(radius / 0.1)          # 0.1 mm candidates: the legal window between two lanes can be under 0.2 mm wide
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x, y = p[0] + i * 0.1, p[1] + j * 0.1
            d = math.hypot(x - p[0], y - p[1])
            if 0.5 <= d <= radius:
                cands.append((d, x, y))
    cands.sort()
    tried = 0
    for d, x, y in cands:
        size = 0.6 if B.via_ok(x, y, net, 0.6) else None      # 0.6/0.3 only: JLCPCB's no-surcharge via
        if size is None:
            continue
        tried += 1
        if tried > tries:
            break
        if B.layer_route(p, (x, y), net, pcbnew.F_Cu, margin=1.5) is not None:
            B.add_via(x, y, net, size)
            return (x, y)
    return None


def connect(B, a, b, netname, avoid=()):
    """Join two points of a net: F.Cu directly if possible, else escape both ends
    to vias and join those on B.Cu, else on In2 (the +3V3 plane layer)."""
    net = next(code for code, ni in B.b.GetNetsByNetcode().items() if ni.GetNetname().split("/")[-1] == netname)
    if math.hypot(a[0] - b[0], a[1] - b[1]) < 12 and B.layer_route(a, b, net, pcbnew.F_Cu, margin=3.0) is not None:
        return "F.Cu"
    va, vb = escape(B, a, net), escape(B, b, net)
    if not va or not vb:
        return f"no escape ({'a' if not va else 'b'})"
    if B.layer_route(va, vb, net, pcbnew.B_Cu, margin=6.0) is not None:
        return "B.Cu"
    return "In2" if B.in2_route(va, vb, net, avoid=avoid) is not None else "failed"


def route2(B, a, b, net, margin=5.0, step=0.1, w=0.15, via_cost=12, a_layers=(pcbnew.F_Cu,), b_layers=(pcbnew.F_Cu,), bbox=None):
    """A* over F.Cu and B.Cu with through vias (0.6/0.3) inside the bounding box of
    a and b (+margin). Obstacles: other-net pads, tracks, vias, keepouts; a via cell
    must be clear on every copper layer. Adds the tracks and vias, returns the layer
    sequence, or None."""
    LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)
    rt, rv = w / 2 + CLR, 0.3 + CLR + 0.003
    if bbox is None:
        bbox = (min(a[0], b[0]) - margin, min(a[1], b[1]) - margin, max(a[0], b[0]) + margin, max(a[1], b[1]) + margin)
    x0 = a[0] - math.ceil((a[0] - bbox[0]) / step) * step
    y0 = a[1] - math.ceil((a[1] - bbox[1]) / step) * step
    x1, y1 = bbox[2], bbox[3]
    nx, ny = int((x1 - x0) / step) + 2, int((y1 - y0) / step) + 2
    blockT = {L: set() for L in LAYERS}
    blockV = set()
    slack = step * 0.5        # a little under the grid's half-diagonal: 0.4 mm pad lanes stay open; every segment is re-checked exactly before it is committed

    def cells_rect(rx0, ry0, rx1, ry1, R):
        for i in range(max(0, int((rx0 - R - x0) / step)), min(nx, int((rx1 + R - x0) / step) + 2)):
            for j in range(max(0, int((ry0 - R - y0) / step)), min(ny, int((ry1 + R - y0) / step) + 2)):
                yield i, j, x0 + i * step, y0 + j * step

    for px0, py0, px1, py1, pn, th in B.pads:
        if pn == net or px1 < x0 - 1 or px0 > x1 + 1 or py1 < y0 - 1 or py0 > y1 + 1:
            continue
        for i, j, cx, cy in cells_rect(px0, py0, px1, py1, rv + slack):
            d = B.rect_dist(px0, py0, px1, py1, cx, cy)
            if d < rv + slack: blockV.add((i, j))
            if d < rt + slack:
                blockT[pcbnew.F_Cu].add((i, j))
                if th: blockT[pcbnew.B_Cu].add((i, j))
    for vx, vy, vr, vn in B.vias:
        if vn == net or not (x0 - 1 <= vx <= x1 + 1 and y0 - 1 <= vy <= y1 + 1):
            continue
        for i, j, cx, cy in cells_rect(vx, vy, vx, vy, vr + rv + slack):
            d = math.hypot(cx - vx, cy - vy) - vr
            if d < rv + slack: blockV.add((i, j))
            if d < rt + slack:
                for L in LAYERS: blockT[L].add((i, j))
    for ax, ay, bx, by, hw, tn, tl in B.tracks:
        if tn == net or max(ax, bx) < x0 - 1 or min(ax, bx) > x1 + 1 or max(ay, by) < y0 - 1 or min(ay, by) > y1 + 1:
            continue
        for i, j, cx, cy in cells_rect(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), hw + rv + slack):
            d = seg_dist(ax, ay, bx, by, cx, cy) - hw
            if d < rv + slack: blockV.add((i, j))          # a via is on every layer, inner-layer tracks included
            if tl in blockT and d < rt + slack: blockT[tl].add((i, j))
    for z in B.rule_areas:
        bb = z.GetBoundingBox()
        for i, j, cx, cy in cells_rect(T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom()), rv):
            inside = z.Outline().Contains(pcbnew.VECTOR2I(MM(cx), MM(cy)))
            near = inside or any(z.Outline().Contains(pcbnew.VECTOR2I(MM(cx + rv * math.cos(k * math.pi / 4)), MM(cy + rv * math.sin(k * math.pi / 4)))) for k in range(8))
            if z.GetDoNotAllowVias() and near: blockV.add((i, j))
            if z.GetDoNotAllowTracks() and (inside or _in_area(z, cx, cy, rt)):
                for L in LAYERS:
                    if z.GetLayerSet().Contains(L): blockT[L].add((i, j))
    # board edge
    for i in range(nx):
        for j in range(ny):
            cx, cy = x0 + i * step, y0 + j * step
            if cx - B.x0 < EDGE + 0.1 or B.x1 - cx < EDGE + 0.1 or cy - B.y0 < EDGE + 0.1 or B.y1 - cy < EDGE + 0.1:
                blockV.add((i, j))
                for L in LAYERS: blockT[L].add((i, j))

    cell = lambda p: (round((p[0] - x0) / step), round((p[1] - y0) / step))
    s, g = cell(a), cell(b)
    for L in LAYERS:
        blockT[L].discard(s); blockT[L].discard(g)
    moves = [(1,0,1),(-1,0,1),(0,1,1),(0,-1,1),(1,1,1.414),(1,-1,1.414),(-1,1,1.414),(-1,-1,1.414)]
    start = [(L, s) for L in a_layers]
    goal = {(L, g) for L in b_layers}
    openq = [(0, 0, n) for n in start]; came = {n: None for n in start}; cost = {n: 0 for n in start}
    end = None; tick = 0
    while openq:
        _, _, c = heapq.heappop(openq)
        if c in goal: end = c; break
        L, (ci, cj) = c
        nbrs = []
        for dx, dy, wt in moves:
            n = (ci + dx, cj + dy)
            if not (0 <= n[0] < nx and 0 <= n[1] < ny) or n in blockT[L]: continue
            if dx and dy and ((ci + dx, cj) in blockT[L] or (ci, cj + dy) in blockT[L]): continue
            turn = 0.4 if came[c] is not None and came[c][0] == L and (dx, dy) != (ci - came[c][1][0], cj - came[c][1][1]) else 0
            nbrs.append(((L, n), wt + turn))
        if (ci, cj) not in blockV:
            for L2 in LAYERS:
                if L2 != L and (ci, cj) not in blockT[L2]: nbrs.append(((L2, (ci, cj)), via_cost))
        for n, wt in nbrs:
            nc = cost[c] + wt
            if nc < cost.get(n, 1e18):
                cost[n] = nc; came[n] = c; tick += 1
                heapq.heappush(openq, (nc + math.hypot(g[0] - n[1][0], g[1] - n[1][1]), tick, n))
    if end is None:
        if getattr(B, "debug", False):
            vis = [(x0 + n[1][0] * step, y0 + n[1][1] * step) for n in cost]
            B.dbg = {'visited': [(n[0], x0 + n[1][0] * step, y0 + n[1][1] * step) for n in cost], 'blockV': [(x0 + i * step, y0 + j * step) for i, j in blockV]}
            print(f"   route2 dbg: visited {len(cost)} nodes, x {min(v[0] for v in vis):.1f}..{max(v[0] for v in vis):.1f}, y {min(v[1] for v in vis):.1f}..{max(v[1] for v in vis):.1f}; goal blocked F/B: {g in blockT[pcbnew.F_Cu]}/{g in blockT[pcbnew.B_Cu]}; grid {nx}x{ny}")
        return None
    path = []; c = end
    while c is not None: path.append(c); c = came[c]
    path.reverse()
    pt = lambda n: (x0 + n[1][0] * step, y0 + n[1][1] * step)
    segs, vias, run = [], [], [path[0]]
    for prev, cur in zip(path, path[1:]):
        if cur[0] != prev[0]:
            segs.append(run); vias.append(pt(prev)); run = [cur]
        else:
            run.append(cur)
    segs.append(run)
    out = []
    for run in segs:
        pts = [run[0]]
        for k in range(1, len(run) - 1):
            d1 = (run[k][1][0] - run[k-1][1][0], run[k][1][1] - run[k-1][1][1]); d2 = (run[k+1][1][0] - run[k][1][0], run[k+1][1][1] - run[k][1][1])
            if d1 != d2: pts.append(run[k])
        if len(run) > 1: pts.append(run[-1])
        out.append((run[0][0], [pt(n) for n in pts]))
    out[0][1][0] = a
    out[-1][1][-1] = b
    # exact validation before committing
    for L, pts in out:
        for p, q in zip(pts, pts[1:]):
            if not B.track_ok(p[0], p[1], q[0], q[1], net, L, w): return None
    for v in vias:
        if not B.via_ok(v[0], v[1], net, 0.6): return None
    for L, pts in out:
        for p, q in zip(pts, pts[1:]): B.add_track(p[0], p[1], q[0], q[1], net, L, w)
    for v in vias: B.add_via(v[0], v[1], net, 0.6)
    return [pcbnew.LayerName(L) for L, _ in out]


def islands_geo(B, net):
    """Islands of a net as geometry: [{'pts': [(x, y, layer|None)], 'vias': n, 'pads': n}]. layer None = any layer."""
    items = []          # (kind, geom, layer)
    for f in B.b.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() == net:
                bb = p.GetBoundingBox()
                items.append(("pad", (T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom()), T(p.GetPosition().x), T(p.GetPosition().y)),
                              None if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD else (pcbnew.F_Cu if p.GetLayerSet().Contains(pcbnew.F_Cu) else pcbnew.B_Cu)))
    for vx, vy, vr, vn in B.vias:
        if vn == net: items.append(("via", (vx, vy), None))
    for ax, ay, bx, by, hw, tn, l in B.tracks:
        if tn == net: items.append(("trk", (ax, ay, bx, by), l))
    par = list(range(len(items)))
    def find(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    def touch(it, x, y, layer):
        k, g, l = it
        if l is not None and layer is not None and l != layer: return False
        if k == "via": return math.hypot(g[0] - x, g[1] - y) < 0.31
        if k == "pad": return B.rect_dist(g[0], g[1], g[2], g[3], x, y) < 0.02
        return seg_dist(g[0], g[1], g[2], g[3], x, y) < 0.02
    for i, it in enumerate(items):
        pts = [(it[1][0], it[1][1]), (it[1][2], it[1][3])] if it[0] == "trk" else ([(it[1][0], it[1][1])] if it[0] == "via" else [])
        for x, y in pts:
            for j, jt in enumerate(items):
                if j != i and touch(jt, x, y, it[2]): par[find(i)] = find(j)
    # pads that overlap (the USB-C receptacle's paired A/B pads) are one node
    pad_idx = [i for i, it in enumerate(items) if it[0] == "pad"]
    for a_ in pad_idx:
        for b_ in pad_idx:
            if a_ < b_:
                ga, gb = items[a_][1], items[b_][1]
                if ga[0] < gb[2] and gb[0] < ga[2] and ga[1] < gb[3] and gb[1] < ga[3] and (items[a_][2] == items[b_][2] or None in (items[a_][2], items[b_][2])):
                    par[find(a_)] = find(b_)
    groups = {}
    for i, it in enumerate(items): groups.setdefault(find(i), []).append(it)
    out = []
    for g in groups.values():
        pts = []
        for k, geo, l in g:
            if k == "pad": pts.append((geo[4], geo[5], l))
            elif k == "via": pts.append((geo[0], geo[1], None))
            else:
                n = max(1, int(math.hypot(geo[2] - geo[0], geo[3] - geo[1]) / 0.5))
                pts += [(geo[0] + (geo[2] - geo[0]) * t / n, geo[1] + (geo[3] - geo[1]) * t / n, l) for t in range(n + 1)]
        out.append({"pts": pts, "vias": sum(1 for it in g if it[0] == "via") + sum(1 for it in g if it[0] == "pad" and it[2] is None),   # a through-hole pad reaches the plane like a via
                    "pads": sum(1 for it in g if it[0] == "pad")})
    return out


def join_islands(B, netname, plane=False, reach=9.0, tries=200, margin=3.5):
    """Connect orphan islands of a net to connected copper. For a plane net every
    island that owns a via counts as connected (the zone joins them)."""
    net = next(code for code, ni in B.b.GetNetsByNetcode().items() if ni.GetNetname().split("/")[-1] == netname)
    both = (pcbnew.F_Cu, pcbnew.B_Cu)
    done = []
    failed = set()
    for _ in range(16):
        isl = islands_geo(B, net)
        if plane:
            good = [i for i in isl if i["vias"]]; orphans = [i for i in isl if not i["vias"]]
        else:
            isl.sort(key=lambda i: -len(i["pts"])); good, orphans = isl[:1], isl[1:]
        orphans = [o for o in orphans if id(o) not in failed and (round(o["pts"][0][0], 2), round(o["pts"][0][1], 2)) not in failed]
        if not orphans: break
        o = orphans[0]
        others = good + [x for x in orphans if x is not o]        # joining two orphans is progress too; connected copper is preferred
        pairs = sorted(((math.hypot(a[0] - b[0], a[1] - b[1]) + (0 if g in good else 1.5), a, b) for a in o["pts"] for g in others for b in g["pts"]), key=lambda p: p[0])
        pairs = [p for p in pairs if 0.3 < p[0] <= reach]
        ok = None
        seen = set()
        for d, a, b in pairs:
            key = (round(a[0], 1), round(a[1], 1), round(b[0], 1), round(b[1], 1))
            if key in seen: continue
            seen.add(key)
            if len(seen) > tries: break
            al = both if a[2] is None else (a[2],)
            bl = both if b[2] is None else (b[2],)
            if pcbnew.In2_Cu in al + bl or pcbnew.In1_Cu in al + bl: continue
            r = route2(B, (a[0], a[1]), (b[0], b[1]), net, margin=margin, a_layers=al, b_layers=bl)
            if r:
                ok = (round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2), r); break
        if ok is None and plane:            # last resort for a plane net: give one of the island's pads its own via
            for x, y, l in o["pts"]:
                if l == pcbnew.F_Cu:
                    v = escape(B, (x, y), net, radius=3.0, tries=60)
                    if v:
                        ok = ("escape", round(x, 2), round(y, 2), v); break
        done.append(ok or ("FAILED", round(o["pts"][0][0], 2), round(o["pts"][0][1], 2), len(pairs)))
        if ok is None:
            failed.add((round(o["pts"][0][0], 2), round(o["pts"][0][1], 2)))
    return done
