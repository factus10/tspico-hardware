#!/usr/bin/env python3
"""Hand-finish helpers for the leftovers Freerouting will not do:
 - drop a via to the GND/+3V3 plane next to a pad or track end (`via` items)
 - route a signal between two points on the +3V3 plane layer In2.Cu, where the
   zone fill flows around it (`in2` items). Never on In1.Cu (GND).
Run with KiCad's Python. Edits tspico-v3.kicad_pcb in place, refills zones.
"""
import heapq, math, sys
import pcbnew

MM = pcbnew.FromMM
T = pcbnew.ToMM
CLR = 0.127
VIA_D, VIA_DRILL = 0.6, 0.3
TW = 0.2                      # signal track width on In2
EDGE = 0.35

def seg_dist(ax, ay, bx, by, px, py):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

class Board:
    def __init__(self, path):
        self.path = path
        self.b = pcbnew.LoadBoard(path)
        bb = self.b.GetBoardEdgesBoundingBox()
        self.x0, self.y0, self.x1, self.y1 = T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())
        self.refresh()

    def refresh(self):
        b = self.b
        self.pads = []      # (x0, y0, x1, y1, net, through)
        for f in b.GetFootprints():
            for p in f.Pads():
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
        r = d / 2 + CLR
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
            if z.GetDoNotAllowTracks() and z.GetLayerSet().Contains(layer) and any(z.Outline().Contains(pcbnew.VECTOR2I(MM(px), MM(py))) for px, py in pts):
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

    def add_via(self, x, y, net, d=VIA_D):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y))); v.SetDrill(MM(0.25 if d < 0.6 else VIA_DRILL)); v.SetWidth(MM(d))
        v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNetCode(net)
        self.b.Add(v)
        self.vias.append((x, y, d / 2, net))

    def add_track(self, ax, ay, bx, by, net, layer, w=TW):
        t = pcbnew.PCB_TRACK(self.b)
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
        x0, y0 = min(a[0], b[0]) - margin, min(a[1], b[1]) - margin
        x1, y1 = max(a[0], b[0]) + margin, max(a[1], b[1]) + margin
        nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
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
