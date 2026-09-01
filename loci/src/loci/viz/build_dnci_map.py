import json, pathlib
sp = pathlib.Path("/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor-loci/b495b991-3549-4a4b-9741-40b94faa1a15/scratchpad")
data = sp.joinpath("dnci_data.json").read_text()

HTML = r"""<title>The Errand Map</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --bg:#eef1ee; --panel:#ffffff; --ink:#16211d; --ink2:#4a5b54; --muted:#7e8e87;
  --line:#dde3df; --accent:#c07a1e; --accent-ink:#8a5510;
  --r0:#e9edea; --r1:#cfe3da; --r2:#97c9b6; --r3:#56a88c; --r4:#2b8168; --r5:#0f5a47;
  --shadow:0 1px 2px rgba(20,33,29,.06),0 8px 24px rgba(20,33,29,.08);
  --canvas:#e7ebe8;
}
:root:not([data-theme="light"]) @media (prefers-color-scheme:dark){}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0d1512; --panel:#152019; --ink:#e8efea; --ink2:#a7b8b0; --muted:#728279;
  --line:#243029; --accent:#e0a24a; --accent-ink:#f0c07e;
  --r0:#1b2621; --r1:#20463a; --r2:#2f6b56; --r3:#489a7d; --r4:#68c2a2; --r5:#9fe0c7;
  --canvas:#0f1815; --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 30px rgba(0,0,0,.35);
}}
:root[data-theme="dark"]{
  --bg:#0d1512; --panel:#152019; --ink:#e8efea; --ink2:#a7b8b0; --muted:#728279;
  --line:#243029; --accent:#e0a24a; --accent-ink:#f0c07e;
  --r0:#1b2621; --r1:#20463a; --r2:#2f6b56; --r3:#489a7d; --r4:#68c2a2; --r5:#9fe0c7;
  --canvas:#0f1815; --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 30px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Public Sans",system-ui,-apple-system,sans-serif;
  display:flex;flex-direction:column;overflow:hidden}
header{padding:14px 20px 12px;border-bottom:1px solid var(--line);
  display:flex;align-items:baseline;gap:18px;flex-wrap:wrap;background:var(--panel)}
h1{font-family:"Archivo",sans-serif;font-weight:800;font-size:20px;letter-spacing:-.02em;
  margin:0;text-wrap:balance}
h1 .tag{color:var(--accent-ink);font-weight:800}
.thesis{color:var(--ink2);font-size:13.5px;max-width:52ch;line-height:1.45;margin:0}
.stats{margin-left:auto;display:flex;gap:22px}
.stat{display:flex;flex-direction:column;align-items:flex-end}
.stat b{font-family:"IBM Plex Mono",monospace;font-weight:500;font-size:17px;
  font-variant-numeric:tabular-nums}
.stat span{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
main{position:relative;flex:1;min-height:0}
#map{position:absolute;inset:0;display:block;background:var(--canvas);cursor:grab;touch-action:none}
#map.drag{cursor:grabbing}
.card{position:absolute;top:16px;left:16px;background:var(--panel);border:1px solid var(--line);
  border-radius:12px;box-shadow:var(--shadow);padding:14px;width:216px}
.card h2{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
  margin:0 0 9px;font-weight:600}
.seg{display:flex;background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:3px;gap:2px}
.seg button{flex:1;border:0;background:transparent;color:var(--ink2);font-family:inherit;
  font-size:12.5px;font-weight:600;padding:7px 4px;border-radius:6px;cursor:pointer;
  transition:background .12s,color .12s}
.seg button[aria-pressed="true"]{background:var(--accent);color:#fff}
:root[data-theme="dark"] .seg button[aria-pressed="true"],
:root:not([data-theme="light"]) .seg button[aria-pressed="true"]{color:#1a130a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .seg button[aria-pressed="true"]{color:#1a130a}}
.sub{font-size:11.5px;color:var(--muted);margin:8px 0 0;line-height:1.4}
.legend{margin-top:14px}
.ramp{height:12px;border-radius:6px;margin:6px 0 5px;
  background:linear-gradient(90deg,var(--r0),var(--r1),var(--r2),var(--r3),var(--r4),var(--r5))}
.ramp-l{display:flex;justify-content:space-between;font-family:"IBM Plex Mono",monospace;
  font-size:10.5px;color:var(--muted)}
.legend .cap{display:flex;justify-content:space-between;font-size:11px;color:var(--ink2);margin-top:3px}
.tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--line);
  border-radius:9px;box-shadow:var(--shadow);padding:9px 11px;font-size:12px;opacity:0;
  transition:opacity .1s;z-index:5;min-width:130px}
.tip .v{font-family:"IBM Plex Mono",monospace;font-size:19px;font-weight:500;line-height:1}
.tip .b{color:var(--ink2);font-size:11.5px;margin-top:3px}
.tip .cat{color:var(--muted);font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;margin-top:6px}
.foot{position:absolute;bottom:12px;right:16px;font-size:10.5px;color:var(--muted);
  background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:5px 9px;opacity:.9}
.hint{position:absolute;bottom:12px;left:16px;font-size:10.5px;color:var(--muted)}
@media (max-width:640px){.stats{width:100%;margin:6px 0 0;justify-content:flex-start}
  .card{width:calc(100% - 32px)}}
</style>

<header>
  <div>
    <h1>The Errand Map <span class="tag">· NYC</span></h1>
  </div>
  <p class="thesis">How completely can you run daily errands on foot? Each hexagon scores its
    walkable access to the 15-category daily-needs bundle — groceries, pharmacy, laundry, and more.</p>
  <div class="stats">
    <div class="stat"><b id="s-median">–</b><span>Median index</span></div>
    <div class="stat"><b id="s-n">–</b><span>Hexes</span></div>
  </div>
</header>

<main>
  <canvas id="map"></canvas>
  <div class="card">
    <h2>Walk budget</h2>
    <div class="seg" id="seg">
      <button data-k="1">5 min</button>
      <button data-k="2" aria-pressed="true">10 min</button>
      <button data-k="3">15 min</button>
    </div>
    <p class="sub" id="sub">Establishments reachable within a 10-minute walk (≈800 m) along the street network.</p>
    <div class="legend">
      <h2 style="margin-bottom:4px">Completeness index</h2>
      <div class="ramp"></div>
      <div class="ramp-l"><span>0.0</span><span>0.5</span><span>1.0</span></div>
      <div class="cap"><span>gap</span><span>complete</span></div>
    </div>
  </div>
  <div class="tip" id="tip"></div>
  <div class="foot">DNCI · weighted geometric mean · deduped POI base</div>
  <div class="hint">drag to pan · scroll to zoom</div>
</main>

<script>
const DATA = __DATA__;
const RAMP = [[233,237,234],[207,227,218],[151,201,182],[86,168,140],[43,129,104],[15,90,71]];
function darkRamp(){ // match dark tokens for legibility on dark canvas
  return [[27,38,33],[32,70,58],[47,107,86],[72,154,125],[104,194,162],[159,224,199]];
}
function isDark(){const t=document.documentElement.getAttribute('data-theme');
  if(t==='dark')return true; if(t==='light')return false;
  return matchMedia('(prefers-color-scheme:dark)').matches;}
function lerp(a,b,t){return a+(b-a)*t}
function color(v){
  const R = isDark()?darkRamp():RAMP;
  v=Math.max(0,Math.min(1,v)); const x=v*(R.length-1); const i=Math.floor(x); const f=x-i;
  const a=R[i], b=R[Math.min(i+1,R.length-1)];
  return `rgb(${Math.round(lerp(a[0],b[0],f))},${Math.round(lerp(a[1],b[1],f))},${Math.round(lerp(a[2],b[2],f))})`;
}
// project lng/lat -> mercator
function mercY(lat){return Math.log(Math.tan(Math.PI/4+lat*Math.PI/360));}
const hexes = DATA.hexes.map(h=>{
  const flat=h[4], pts=[];
  for(let i=0;i<flat.length;i+=2){pts.push([flat[i], mercY(flat[i+1])]);}
  return {boro:h[0], d:[0,h[1],h[2],h[3]], pts};
});
// data bounds
let minX=1e9,maxX=-1e9,minY=1e9,maxY=-1e9;
for(const h of hexes) for(const p of h.pts){
  if(p[0]<minX)minX=p[0]; if(p[0]>maxX)maxX=p[0];
  if(p[1]<minY)minY=p[1]; if(p[1]>maxY)maxY=p[1];
}
const cX=(minX+maxX)/2, cY=(minY+maxY)/2;
const cv=document.getElementById('map'), ctx=cv.getContext('2d');
const pick=document.createElement('canvas'), pctx=pick.getContext('2d',{willReadFrequently:true});
let W=0,H=0,dpr=1,base=1, view={zoom:1,px:0,py:0}, kIndex=2;
function resize(){
  const r=cv.getBoundingClientRect(); W=r.width; H=r.height; dpr=Math.min(devicePixelRatio||1,2);
  cv.width=W*dpr; cv.height=H*dpr; ctx.setTransform(dpr,0,0,dpr,0,0);
  pick.width=W; pick.height=H;
  base=Math.min(W/(maxX-minX), H/(maxY-minY))*0.94;
  draw();
}
function sx(x){return (x-cX)*base*view.zoom + W/2 + view.px;}
function sy(y){return (cY-y)*base*view.zoom + H/2 + view.py;}
function draw(){
  ctx.clearRect(0,0,W,H);
  const dk=isDark();
  ctx.lineWidth=Math.max(.25, .6*Math.min(view.zoom,2)); ctx.lineJoin='round';
  ctx.strokeStyle=dk?'rgba(0,0,0,.35)':'rgba(255,255,255,.55)';
  for(const h of hexes){
    const p=h.pts; ctx.beginPath();
    ctx.moveTo(sx(p[0][0]),sy(p[0][1]));
    for(let i=1;i<p.length;i++) ctx.lineTo(sx(p[i][0]),sy(p[i][1]));
    ctx.closePath();
    ctx.fillStyle=color(h.d[kIndex]); ctx.fill();
    if(view.zoom>1.3) ctx.stroke();
  }
}
function drawPick(){
  pctx.clearRect(0,0,W,H); pctx.lineWidth=0;
  for(let idx=0;idx<hexes.length;idx++){
    const p=hexes[idx].pts; const id=idx+1;
    pctx.fillStyle=`rgb(${(id>>16)&255},${(id>>8)&255},${id&255})`;
    pctx.beginPath(); pctx.moveTo(sx(p[0][0]),sy(p[0][1]));
    for(let i=1;i<p.length;i++) pctx.lineTo(sx(p[i][0]),sy(p[i][1]));
    pctx.closePath(); pctx.fill();
  }
  pickDirty=false;
}
let pickDirty=true;
function scheduleDraw(){draw(); pickDirty=true;}
// interaction
let dragging=false, lx=0, ly=0, moved=false;
cv.addEventListener('pointerdown',e=>{dragging=true;moved=false;lx=e.clientX;ly=e.clientY;
  cv.classList.add('drag');cv.setPointerCapture(e.pointerId);});
cv.addEventListener('pointermove',e=>{
  if(dragging){view.px+=e.clientX-lx; view.py+=e.clientY-ly; lx=e.clientX; ly=e.clientY;
    moved=true; scheduleDraw(); tip.style.opacity=0; return;}
  hover(e);
});
cv.addEventListener('pointerup',e=>{dragging=false;cv.classList.remove('drag');});
cv.addEventListener('pointerleave',()=>{tip.style.opacity=0;});
cv.addEventListener('wheel',e=>{e.preventDefault();
  const r=cv.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  const f=Math.exp(-e.deltaY*0.0016), nz=Math.max(1,Math.min(60,view.zoom*f));
  const k=nz/view.zoom;
  view.px = mx - (mx-view.px)*k - (W/2 - view.px*1)*0 ; // adjust about cursor
  view.px = mx - (mx - view.px)*k; view.py = my - (my - view.py)*k;
  view.zoom=nz; scheduleDraw(); tip.style.opacity=0;
},{passive:false});
const tip=document.getElementById('tip');
const BNAMES=DATA.boroughs;
function hover(e){
  if(pickDirty) drawPick();
  const r=cv.getBoundingClientRect(), x=Math.round(e.clientX-r.left), y=Math.round(e.clientY-r.top);
  if(x<0||y<0||x>=W||y>=H){tip.style.opacity=0;return;}
  const px=pctx.getImageData(x,y,1,1).data; const id=(px[0]<<16)|(px[1]<<8)|px[2];
  if(id<=0||id>hexes.length){tip.style.opacity=0;return;}
  const h=hexes[id-1], v=h.d[kIndex];
  tip.innerHTML=`<div class="v" style="color:${color(v)}">${v.toFixed(2)}</div>`+
    `<div class="b">${BNAMES[h.boro]||'—'}</div>`+
    `<div class="cat">completeness index</div>`;
  const tx=Math.min(e.clientX-r.left+16, W-150), ty=Math.min(e.clientY-r.top+14, H-70);
  tip.style.left=tx+'px'; tip.style.top=ty+'px'; tip.style.opacity=1;
}
// controls
const SUBS={1:'Establishments reachable within a 5-minute walk (≈400 m) along the street network.',
  2:'Establishments reachable within a 10-minute walk (≈800 m) along the street network.',
  3:'Establishments reachable within a 15-minute walk (≈1200 m) along the street network.'};
document.getElementById('seg').addEventListener('click',e=>{
  const b=e.target.closest('button'); if(!b)return;
  [...e.currentTarget.children].forEach(x=>x.setAttribute('aria-pressed', x===b));
  kIndex=+b.dataset.k; document.getElementById('sub').textContent=SUBS[kIndex];
  document.getElementById('s-median').textContent=DATA.median[[,'5','10','15'][kIndex]].toFixed(2);
  scheduleDraw();
});
document.getElementById('s-n').textContent=DATA.n.toLocaleString();
document.getElementById('s-median').textContent=DATA.median['10'].toFixed(2);
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>scheduleDraw());
new MutationObserver(()=>scheduleDraw()).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
addEventListener('resize',resize);
resize();
</script>
"""
out = HTML.replace("__DATA__", data)
pathlib.Path("/Users/abenmayor/Documents/Projects/abenmayor/loci/output_errand_map.html")
target = sp/"errand_map.html"
target.write_text(out)
print("wrote", target, len(out)//1024, "KB")
