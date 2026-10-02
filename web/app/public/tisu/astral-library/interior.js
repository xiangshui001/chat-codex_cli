/** Close-up interior pieces, sharing the original instanced voxel batches. */
export function addInteriorDetails({C, b, panel, inside, shell, archY, solid}) {
  const oak = '#a47c4e', ink = '#334b59', parchment = '#f5e9c8', red = '#976346';
  let books = 0;
  function book(p, x, y, z, w, d, color) {
    p(x, y, z, w, .13, d, color);
    p(x, y + .01, z + d / 2, w * .84, .075, .025, C.paper);
    for (const s of [-1, 1]) p(x + s * w * .37, y + .077, z, .035, .014, d * .86, C.gold);
    books++;
  }
  function chart(p, x, y, z, w = .82, d = .57) {
    p(x, y, z, w, .025, d, parchment);
    for (const s of [-1, 1]) {
      p(x + s * w * .43, y + .017, z, .018, .006, d * .9, C.gold);
      p(x, y + .017, z + s * d * .41, w * .88, .006, .018, C.gold);
    }
    for (let j = 0; j < 12; j++) {
      const a = j * Math.PI / 6;
      p(x + Math.cos(a) * w * .24, y + .02, z + Math.sin(a) * d * .24, .027, .008, .027, ink);
    }
    for (let j = 0; j < 9; j++) p(x - w * .25 + j * w * .06, y + .02, z - d * .15 + j * d * .032, .035, .008, .022, C.blue);
  }
  function rug(x, z, y, w, d) {
    b(x, y + .018, z, w, .025, d, C.blue, inside);
    for (const s of [-1, 1]) {
      b(x + s * (w / 2 - .13), y + .035, z, .045, .012, d - .13, C.gold, inside);
      b(x, y + .035, z + s * (d / 2 - .13), w - .13, .012, .045, C.gold, inside);
      for (let j = 0; j < 18; j++) b(x - w / 2 + .12 + j * (w - .24) / 17, y + .025, z + s * (d / 2 + .1), .035, .015, .2, C.paper, inside);
    }
    for (let i = -2; i <= 2; i++) for (let j = -3; j <= 3; j++) {
      const xx = x + i * w * .13, zz = z + j * d * .105;
      for (const s of [-1, 1]) b(xx + s * .085, y + .036, zz, .065, .01, .065, C.gold, inside);
      b(xx, y + .037, zz, .075, .012, .075, C.bright, inside);
    }
  }

  // Close-range table ornament: celestial charts, rulers, magnifiers, wax seals and clock faces.
  const desks = [];
  for (const z of [-7, -1, 5]) for (const x of [-4.2, 4.2]) desks.push([x, z, .9, 3.6]);
  for (const y of [7.9, 14.9]) for (const z of [-6, 4]) desks.push([-12.8, z, y, 2.8]);
  for (const [x, z, y, w] of desks) {
    const p = panel(x, z, 0, inside), top = y + 1.66;
    chart(p, -.93, top, -.7, .68, .47);
    p(-.93, top + .022, -.94, .67, .018, .032, oak);
    for (let j = 0; j < 12; j++) p(-1.23 + j * .052, top + .035, -.935, .012, .008, j % 3 ? .024 : .04, C.gold);
    for (let j = 0; j < 20; j++) {
      const a = j * Math.PI / 10;
      p(-.45 + Math.cos(a) * .13, top + .038, -.68 + Math.sin(a) * .13, .027, .025, .027, C.gold, 'metal');
    }
    p(-.29, top + .038, -.68, .15, .04, .052, C.dark);
    p(-.8, top + .015, .82, .25, .025, .19, parchment);
    for (let j = 0; j < 8; j++) {
      const a = j * Math.PI / 4;
      p(-.78 + Math.cos(a) * .061, top + .034, .82 + Math.sin(a) * .061, .05, .018, .05, red);
    }
    p(-.77, top + .047, .82, .025, .008, .025, C.gold);
    p(w / 2 - .21, top + .1, -.66, .31, .12, .24, C.wood);
    p(w / 2 - .21, top + .3, -.66, .29, .31, .1, C.gold, 'metal');
    p(w / 2 - .21, top + .3, -.599, .23, .23, .015, C.paper);
    p(w / 2 - .21, top + .338, -.587, .016, .084, .015, ink);
    p(w / 2 - .18, top + .298, -.587, .084, .016, .015, ink);
    // Floral relief beneath the long edge, with carved corner brackets.
    for (const side of [-1, 1]) {
      p(side * (w / 2 - .21), y + .91, 1.09, .32, .29, .12, oak);
      for (let j = 0; j < 7; j++) {
        const a = j * .5;
        p(side * (w / 2 - .21) + Math.sin(a) * .1, y + .91 + Math.cos(a) * .09, 1.16, .045, .065, .035, C.gold);
      }
    }
  }

  // Shelf end bands and brass catalogue plates at the ends of each bay.
  for (const [level, y] of [0.9, 7.9, 14.9].entries()) {
    for (const side of [-1, 1]) for (const z of [-12, -6, 0, 6, 10.5]) {
      const p = panel(side * 17.3, z, -side * Math.PI / 2, inside);
      const h = level === 2 ? 2.2 : 6.06;
      p(0, y + h - .55, 1.04, 1.06, .25, .055, C.gold, 'metal');
      p(0, y + h - .55, 1.076, .91, .15, .016, C.blue);
      for (let j = 0; j < 7; j++) p(-.34 + j * .112, y + h - .55, 1.091, .048, .052 + (j % 3) * .012, .008, C.paper);
      for (const edge of [-1, 1]) for (let j = 0; j < (level === 2 ? 4 : 13); j++) {
        const yy = y + .8 + j * (level === 2 ? .23 : .36);
        p(edge * (z === 10.5 ? 1.49 : 2.34), yy, .99, .075, .21, .07, C.gold, 'metal');
      }
    }
  }

  // The catalog desk gains card labels, a tied ledger bundle, and stacked registers.
  const catalog = panel(-12.4, 10.5, 0, inside);
  for (let i = 0; i < 8; i++) for (let j = 0; j < 3; j++) {
    const x = -1.75 + i * .5, y = 1.12 + j * .28;
    catalog(x, y + .058, .744, .19, .072, .02, C.gold, 'metal');
    catalog(x, y + .058, .759, .13, .044, .008, parchment);
    catalog(x, y + .061, .765, .075, .008, .004, ink);
  }
  for (let j = 0; j < 4; j++) book(catalog, .89, 2.23 + j * .14, -.2, .75, .51, [C.blue, red, C.green, oak][j]);
  chart(catalog, -.36, 2.34, .25, .65, .46);
  catalog(.89, 2.8, -.2, .07, .025, .54, C.gold);

  // A glass cabinet of rare volumes; the camera aisle remains clear.
  const exhibit = panel(-12.3, -9.4, 0, inside);
  exhibit(0, 1.58, 0, 3.55, 1.35, 1.48, C.wood);
  exhibit(0, 2.33, 0, 3.79, .17, 1.72, C.wood2);
  exhibit(0, 2.84, 0, 3.55, .87, 1.46, C.glass, 'glass');
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) exhibit(sx * 1.77, 2.87, sz * .73, .07, .93, .07, C.gold, 'metal');
  exhibit(0, 3.34, 0, 3.73, .07, 1.63, C.gold);
  for (const side of [-1, 1]) {
    exhibit(side * .91, 1.63, .773, 1.42, .76, .035, oak);
    exhibit(side * .91, 1.63, .796, 1.18, .56, .025, C.dark);
    exhibit(side * .91, 1.63, .816, 1.08, .46, .02, C.wood2);
    book(exhibit, side * .87, 2.51, 0, 1.04, .71, side < 0 ? C.blue : red);
    chart(exhibit, side * .87, 2.6, 0, .84, .58);
  }
  exhibit(0, 2.2, .87, .73, .17, .06, C.gold);
  exhibit(0, 2.2, .91, .62, .1, .02, C.blue);
  solid(-12.3, -9.4, 3.8, 1.75, 0);

  // Needlepoint rugs beneath the quiet gallery niches.
  for (const y of [7.9, 14.9]) for (const z of [-9, 1]) rug(-14.7, z + .65, y + .01, 3.3, 2.8);

  // Star atlas cabinet on the rear third-floor bridge, behind the authored camera track.
  const atlas = panel(0, -14.5, 0, inside);
  atlas(0, 15.75, 0, 2.4, 1.25, 1.08, C.wood);
  atlas(0, 16.43, 0, 2.64, .15, 1.25, C.wood2);
  atlas(0, 16.91, 0, 2.4, .81, 1.07, C.glass, 'glass');
  for (const side of [-1, 1]) {
    atlas(side * 1.2, 16.95, .54, .065, .9, .065, C.gold, 'metal');
    atlas(side * .63, 15.8, .57, .98, .71, .06, oak);
    atlas(side * .63, 15.8, .616, .8, .53, .025, C.dark);
    atlas(side * .63, 15.8, .64, .72, .45, .019, C.wood2);
  }
  atlas(0, 17.39, 0, 2.57, .075, 1.22, C.gold);
  chart(atlas, -.51, 16.65, 0, .85, .72);
  book(atlas, .61, 16.59, 0, .76, .59, C.blue);
  book(atlas, .61, 16.76, 0, .72, .54, red);
  solid(0, -14.5, 2.7, 1.3, 2);

  // Leaded colored glass inside the existing rear lancet opening.
  const rear = panel(0, -16.02, 0, shell);
  const r = 5.7, spring = 1 + 19 - Math.sqrt(3) * r;
  for (let x = -4.95; x <= 4.96; x += .9) for (let y = 2.5; y <= 18.7; y += 1.05) {
    if (y + .5 > archY(x, r, spring) - .3) continue;
    const color = [C.blue, C.glass, red, C.gold][Math.abs(Math.round(x * 2 + y)) % 4];
    rear(x, y, .12, .8, .94, .035, color, 'glass');
    rear(x, y - .5, .16, .9, .025, .037, C.gold, 'metal');
    rear(x - .435, y, .16, .025, 1.05, .037, C.gold, 'metal');
    if (Math.round(y) % 3 === 0) rear(x, y, .17, .085, .085, .043, C.bright, 'metal');
  }
  return {books};
}
