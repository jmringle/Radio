// The heard map's zoom: wheel and pinch zoom toward the pointer, drag to pan, and + − Fit World
// buttons. It only changes the map's viewBox (map degrees: x = longitude + 180, y = 90 - latitude);
// it sends and fetches nothing. Without it, the map shows the server's fitted view.
(() => {
  const svg = document.querySelector("svg.map");
  const controls = document.querySelector(".zoom");
  if (!svg || !controls) return;
  const parse = (text) => text.split(" ").map(Number);
  const world = parse(svg.dataset.world);
  const ratio = world[3] / world[2]; // every view keeps the map's shape, so the map never resizes
  const MIN_WIDTH = 6; // degrees: three squares across; closer shows nothing new
  const STEP = 1.5; // one button press
  let view = parse(svg.getAttribute("viewBox"));

  // Show the view at (x, y), `width` degrees wide, kept within the zoom limits and the map's edges.
  function show(x, y, width) {
    const w = Math.min(Math.max(width, MIN_WIDTH), world[2]);
    const h = w * ratio;
    view = [
      Math.min(Math.max(x, world[0]), world[0] + world[2] - w),
      Math.min(Math.max(y, world[1]), world[1] + world[3] - h),
      w, h,
    ];
    svg.setAttribute("viewBox", view.map((n) => +n.toFixed(4)).join(" "));
  }

  // Zoom in by `factor` (below 1: out), keeping the map point at fraction (fx, fy) of the view in place.
  function zoom(factor, fx = 0.5, fy = 0.5) {
    const [x, y, w, h] = view;
    const nw = Math.min(Math.max(w / factor, MIN_WIDTH), world[2]);
    show(x + (w - nw) * fx, y + (h - nw * ratio) * fy, nw);
  }

  // A screen point as a fraction of the map's box on screen.
  function fraction(clientX, clientY) {
    const r = svg.getBoundingClientRect();
    return [(clientX - r.left) / r.width, (clientY - r.top) / r.height];
  }

  const actions = {
    in: () => zoom(STEP),
    out: () => zoom(1 / STEP),
    fit: () => { const [x, y, w] = parse(svg.dataset.fit); show(x, y, w); },
    world: () => show(world[0], world[1], world[2]),
  };
  controls.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-zoom]");
    if (button) actions[button.dataset.zoom]();
  });
  controls.hidden = false;

  // Wheel, and pinch on a trackpad (sent as a wheel with ctrlKey): zoom toward the pointer.
  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom(Math.exp(-event.deltaY * 0.002), ...fraction(event.clientX, event.clientY));
  }, { passive: false });

  // One pointer drags the map; two (a touch pinch) zoom about their midpoint as they spread or close.
  const pointers = new Map();
  let last = null; // the previous midpoint and spread
  function gesture() {
    const points = [...pointers.values()];
    const x = points.reduce((sum, p) => sum + p.x, 0) / points.length;
    const y = points.reduce((sum, p) => sum + p.y, 0) / points.length;
    const spread = points.length > 1 ? Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) : 0;
    return { x, y, spread };
  }
  svg.addEventListener("pointerdown", (event) => {
    svg.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    last = gesture();
  });
  svg.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const now = gesture();
    const scale = view[2] / svg.getBoundingClientRect().width; // degrees per screen pixel
    show(view[0] - (now.x - last.x) * scale, view[1] - (now.y - last.y) * scale, view[2]);
    if (last.spread && now.spread) zoom(now.spread / last.spread, ...fraction(now.x, now.y));
    last = now;
  });
  const lift = (event) => {
    pointers.delete(event.pointerId);
    last = pointers.size ? gesture() : null;
  };
  svg.addEventListener("pointerup", lift);
  svg.addEventListener("pointercancel", lift);
})();
