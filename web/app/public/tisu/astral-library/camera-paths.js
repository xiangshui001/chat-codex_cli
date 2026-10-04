/** Camera positions and look targets, in the building's world units. Edit these to choreograph a visit. */
const point = (position, target, duration, floor, label) => ({position, target, duration, floor, label});

const doorway = [
  point([0, 4.2, 22], [0, 7, 2], 0, 0, '门前'),
  point([0, 3.25, 11.5], [0, 7.5, -6], 4, 0, '门厅'),
  point([0, 3.05, 8], [0, 8, -9], 3, 0, '中央书厅')
];
const reading = [
  point([0, 3.15, 6.8], [-4.2, 2.6, 5], 0, 0, '阅览桌'),
  point([-1.65, 3.15, 3.2], [-4.2, 2.6, 5], 4, 0, '书页与铜灯'),
  point([-1.65, 3.15, -2.8], [-4.2, 2.6, -1], 5, 0, '星图与手稿'),
  point([0, 3.5, -10], [0, 12.5, -16], 5, 0, '彩窗书厅')
];

export const LIBRARY_CAMERA_PATHS = {
  entrance: doorway,
  reading,
  gallery: [
    point([-10.1, 10.05, 8.3], [-12.8, 9.7, 4], 0, 1, '二层阅览角'),
    point([-10.1, 10.05, 1.2], [-12.8, 9.7, -6], 5, 1, '典藏回廊'),
    point([-10.1, 10.05, -12.9], [0, 11.5, 2], 7, 1, '回廊远眺'),
    point([-5.5, 10.05, -12.9], [0, 15, 4], 4, 1, '穹顶与灯环')
  ],
  upper: [
    point([-5.5, 17.05, -12.8], [0, 16.9, -14.4], 0, 2, '星图典藏'),
    point([-2.2, 17.05, -12.8], [0, 16.9, -14.4], 5, 2, '古卷展柜'),
    point([-5.5, 17.05, -12.8], [0, 14, 3], 5, 2, '三层俯瞰')
  ],
  tour: [
    ...doorway,
    point([0, 3.15, 1.8], [-4.2, 2.6, -1], 4, 0, '阅读大厅'),
    point([-1.65, 3.15, -2.8], [-4.2, 2.6, -1], 3, 0, '星图与手稿'),
    point([0, 3.5, -10], [0, 12.5, -16], 5, 0, '彩窗书厅'),
    point([10.1, 3.25, -9.7], [17.3, 4.1, -12], 4, 0, '整墙藏书'),
    point([10.1, 3.25, 11.35], [13.5, 6.5, -4], 6, 0, '右侧楼梯'),
    point([13.5, 3.05, 11.35], [13.5, 8, -4], 2, 0, '楼梯起点'),
    point([13.5, 3.05, 10], [13.5, 8, -4], 1, 0, '登上二层'),
    point([13.5, 10.05, -4.5], [10.1, 11, -10], 7, 1, '二层典藏'),
    point([10.1, 10.05, -5.2], [0, 13, -4], 2, 1, '回廊与灯环'),
    point([10.1, 10.05, -8.7], [0, 12.5, -2], 3, 1, '中央穹顶'),
    point([5.5, 11.8, -8.7], [0, 15, -7], 4, 1, '灯环与穹顶'),
    point([5.5, 17.05, -8.7], [0, 16, -7], 4, 2, '抬升至三层'),
    point([5.5, 17.05, -12.8], [0, 16.9, -14.4], 4, 2, '古卷展柜'),
    point([-5.5, 17.05, -12.8], [0, 16.9, -14.4], 6, 2, '星图典藏'),
    point([-5.5, 17.05, -12.8], [0, 14, 3], 3, 2, '群星之下')
  ]
};

/** Piecewise straight camera moves cannot overshoot their authored corridor. */
export function createCameraPath(waypoints) {
  if (!Array.isArray(waypoints) || waypoints.length < 2) throw new Error('A camera path needs at least two waypoints');
  const points = waypoints.map((p, i) => {
    for (const key of ['position', 'target']) {
      if (!Array.isArray(p[key]) || p[key].length !== 3 || !p[key].every(Number.isFinite)) throw new Error('Invalid camera ' + key);
    }
    if (Math.hypot(...p.position.map((v, j) => v - p.target[j])) < .01) throw new Error('Camera target must differ from its position');
    const duration = i === 0 ? 0 : (p.duration ?? 3);
    if (!Number.isFinite(duration) || (i > 0 && duration <= 0)) throw new Error('Camera duration must be positive');
    const floor = p.floor ?? 0;
    if (![0, 1, 2].includes(floor)) throw new Error('Invalid camera floor');
    return {...p, position: [...p.position], target: [...p.target], duration, floor, label: String(p.label ?? '')};
  });
  const duration = points.reduce((total, p) => total + p.duration, 0);
  function sample(time) {
    if (!Number.isFinite(time)) throw new Error('Invalid camera time');
    const elapsed = Math.max(0, Math.min(duration, time));
    let start = 0;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i], end = start + b.duration;
      if (elapsed <= end || i === points.length - 1) {
        const t = Math.max(0, Math.min(1, (elapsed - start) / b.duration));
        const s = t * t * (3 - 2 * t);
        const mix = key => a[key].map((value, j) => value + (b[key][j] - value) * s);
        return {position: mix('position'), target: mix('target'), floor: t < .5 ? a.floor : b.floor, label: t === 0 ? a.label : b.label, progress: elapsed / duration};
      }
      start = end;
    }
  }
  return {points, duration, sample};
}
