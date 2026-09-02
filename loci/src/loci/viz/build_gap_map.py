import json, pathlib
sp = pathlib.Path("/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor-loci/b495b991-3549-4a4b-9741-40b94faa1a15/scratchpad")
data = sp.joinpath("gaps_data.json").read_text()

HTML = r"""<title>The Missing Business</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --bg:#f2efe9; --panel:#fffdf9; --ink:#1c1a16; --ink2:#57524a; --muted:#8c867a;
  --line:#e2ddd2; --canvas:#e9e5dc; --context:#d7d2c6; --accent:#b5541f;
  --shadow:0 1px 2px rgba(28,26,22,.06),0 10px 30px rgba(28,26,22,.09);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#14120f; --panel:#1c1a15; --ink:#efe9df; --ink2:#b3aa9a; --muted:#7c7566;
  --line:#2a271f; --canvas:#100f0c; --context:#2b2820; --accent:#e08a4a;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 12px 34px rgba(0,0,0,.4);
}}
:root[data-theme="dark"]{
  --bg:#14120f; --panel:#1c1a15; --ink:#efe9df; --ink2:#b3aa9a; --muted:#7c7566;
  --line:#2a271f; --canvas:#100f0c; --context:#2b2820; --accent:#e08a4a;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 12px 34px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Public Sans",system-ui,sans-serif;display:flex;flex-direction:column;overflow:hidden}
header{padding:13px 20px 12px;border-bottom:1px solid var(--line);background:var(--panel);
  display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
h1{font-family:"Archivo",sans-serif;font-weight:800;font-size:19px;letter-spacing:-.02em;margin:0}
.thesis{color:var(--ink2);font-size:13px;max-width:56ch;line-height:1.45;margin:0}
.stat{margin-left:auto;text-align:right}
.stat b{font-family:"IBM Plex Mono",monospace;font-size:16px;font-variant-numeric:tabular-nums;display:block}
.stat span{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
main{flex:1;min-height:0;display:flex}
.side{width:250px;border-right:1px solid var(--line);background:var(--panel);overflow-y:auto;padding:12px}
.side h2{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:2px 0 8px;font-weight:600}
.opt{display:flex;align-items:center;gap:9px;width:100%;border:0;background:transparent;
  color:var(--ink);font-family:inherit;font-size:13px;text-align:left;padding:7px 8px;border-radius:8px;cursor:pointer}
.opt:hover{background:var(--bg)}
.opt[aria-pressed="true"]{background:var(--bg);font-weight:600}
.opt .sw{width:11px;height:11px;border-radius:3px;flex:none}
.opt .n{margin-left:auto;font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.opt[aria-pressed="true"] .n{color:var(--ink2)}
.mapwrap{position:relative;flex:1;min-width:0}
#map{position:absolute;inset:0;display:block;background:var(--canvas);cursor:grab;touch-action:none}
#map.drag{cursor:grabbing}
.tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--line);
  border-radius:10px;box-shadow:var(--shadow);padding:10px 12px;font-size:12px;opacity:0;transition:opacity .1s;z-index:5;max-width:220px}
.tip .nb{font-weight:700;font-size:13px}
.tip .pop{color:var(--ink2);font-size:11.5px;margin-top:1px}
.tip .mi{margin-top:7px;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.tip .biz{display:inline-block;margin:3px 4px 0 0;padding:2px 7px;border-radius:5px;font-size:11.5px;
  font-weight:600;color:#fff}
.hint{position:absolute;bottom:12px;left:14px;font-size:10.5px;color:var(--muted)}
.foot{position:absolute;bottom:12px;right:14px;font-size:10px;color:var(--muted);background:var(--panel);
  border:1px solid var(--line);border-radius:6px;padding:4px 8px}
@media (max-width:720px){.side{width:170px}.thesis{display:none}}
</style>

<header>
  <h1>The Missing Business</h1>
  <p class="thesis">Walkable, lived-in NYC areas that lack one business their neighbors all have.
    Pick a business — every area missing it lights up. The gap is the opening.</p>
  <div class="stat"><b id="s-n">–</b><span id="s-l">areas missing it</span></div>
</header>
<main>
  <aside class="side">
    <h2>Show areas missing…</h2>
    <div id="opts"></div>
    <h2 style="margin-top:16px">Read</h2>
    <p style="font-size:11.5px;color:var(--ink2);line-height:1.5;margin:0">
      A business counts as a gap only if <b>80%+</b> of walkable areas have it, so its absence is
      conspicuous — not a rare specialty. Faint hexes are populated areas with no such gap.
      Coverage caveat: a "missing" bodega may be a data hole; validate a shortlist before acting.</p>
  </aside>
  <div class="mapwrap">
    <canvas id="map"></canvas>
    <div class="tip" id="tip"></div>
    <div class="hint">drag to pan · scroll to zoom · hover a hex</div>
    <div class="foot">648 gap hexes · 10-min walk · ranked context by population</div>
  </div>
</main>

<script>
const DATA = __DATA__;
const CATS = DATA.cats, LABELS = DATA.catLabels;
// distinct color per business (shown one-at-a-time when filtered; legend labels avoid color-alone)
const COLORS = {
  hardware:"#b5541f", convenience:"#2f7d5c", clinic:"#3d6fb4", fitness:"#c69a1e",
  childcare:"#9350a6", laundry:"#2aa1a8", pharmacy:"#cc4b63", hair_barber:"#6d8b3a",
  cafe_bakery:"#8a6d4b", grocery:"#417a2f", nails_beauty:"#b3689a", bar:"#7a5cc0",
  bank:"#4a7a8c", tailor_repair:"#996a3a"
};
function catColor(i){return COLORS[CATS[i]]||"#b5541f";}
function isDark(){const t=document.documentElement.getAttribute('data-theme');
  if(t==='dark')return true; if(t==='light')return false; return matchMedia('(prefers-color-scheme:dark)').matches;}

function mercY(lat){return Math.log(Math.tan(Math.PI/4+lat*Math.PI/360));}
const hexes = DATA.hexes.map(h=>{
  const flat=h[4], pts=[]; for(let i=0;i<flat.length;i+=2) pts.push([flat[i], mercY(flat[i+1])]);
  return {lead:h[0], mask:h[1], pop:h[2], nta:h[3], pts};
});
let minX=1e9,maxX=-1e9,minY=1e9,maxY=-1e9;
for(const h of hexes) for(const p of h.pts){ if(p[0]<minX)minX=p[0];if(p[0]>maxX)maxX=p[0];if(p[1]<minY)minY=p[1];if(p[1]>maxY)maxY=p[1];}
const cX=(minX+maxX)/2, cY=(minY+maxY)/2;

const cv=document.getElementById('map'), ctx=cv.getContext('2d');
const pick=document.createElement('canvas'), pctx=pick.getContext('2d',{willReadFrequently:true});
let W=0,H=0,dpr=1,base=1,view={zoom:1,px:0,py:0}, filter=-1, pickDirty=true; // filter -1 = all gaps
function resize(){const r=cv.getBoundingClientRect();W=r.width;H=r.height;dpr=Math.min(devicePixelRatio||1,2);
  cv.width=W*dpr;cv.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);pick.width=W;pick.height=H;
  base=Math.min(W/(maxX-minX),H/(maxY-minY))*0.94;draw();}
function sx(x){return (x-cX)*base*view.zoom+W/2+view.px;}
function sy(y){return (cY-y)*base*view.zoom+H/2+view.py;}
function shown(h){ // is this hex highlighted under the current filter?
  if(h.lead<0) return false;
  if(filter<0) return true;            // all gaps
  return (h.mask>>filter)&1;           // missing this specific business
}
function fill(h){
  if(!shown(h)) return null;
  return filter<0 ? catColor(h.lead) : catColor(filter);
}
function draw(){
  ctx.clearRect(0,0,W,H); const ctxt=getComputedStyle(document.body).getPropertyValue('--context');
  ctx.lineJoin='round';
  // context first (populated, no gap), then highlights on top
  for(const pass of [0,1]){
    for(const h of hexes){
      const hl=fill(h); if(pass===0 && hl) continue; if(pass===1 && !hl) continue;
      const p=h.pts; ctx.beginPath(); ctx.moveTo(sx(p[0][0]),sy(p[0][1]));
      for(let i=1;i<p.length;i++) ctx.lineTo(sx(p[i][0]),sy(p[i][1])); ctx.closePath();
      ctx.fillStyle = hl || ctxt; ctx.globalAlpha = hl?0.92:0.5; ctx.fill();
    }
  }
  ctx.globalAlpha=1;
}
function drawPick(){pctx.clearRect(0,0,W,H);
  for(let idx=0;idx<hexes.length;idx++){const p=hexes[idx].pts;const id=idx+1;
    pctx.fillStyle=`rgb(${(id>>16)&255},${(id>>8)&255},${id&255})`;
    pctx.beginPath();pctx.moveTo(sx(p[0][0]),sy(p[0][1]));
    for(let i=1;i<p.length;i++)pctx.lineTo(sx(p[i][0]),sy(p[i][1]));pctx.closePath();pctx.fill();}
  pickDirty=false;}
function redraw(){draw();pickDirty=true;}
let dragging=false,lx=0,ly=0;
cv.addEventListener('pointerdown',e=>{dragging=true;lx=e.clientX;ly=e.clientY;cv.classList.add('drag');cv.setPointerCapture(e.pointerId);});
cv.addEventListener('pointermove',e=>{if(dragging){view.px+=e.clientX-lx;view.py+=e.clientY-ly;lx=e.clientX;ly=e.clientY;redraw();tip.style.opacity=0;return;}hover(e);});
cv.addEventListener('pointerup',()=>{dragging=false;cv.classList.remove('drag');});
cv.addEventListener('pointerleave',()=>{tip.style.opacity=0;});
cv.addEventListener('wheel',e=>{e.preventDefault();const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const nz=Math.max(1,Math.min(60,view.zoom*Math.exp(-e.deltaY*0.0016))),k=nz/view.zoom;
  view.px=mx-(mx-view.px)*k;view.py=my-(my-view.py)*k;view.zoom=nz;redraw();tip.style.opacity=0;},{passive:false});
const tip=document.getElementById('tip');
function hover(e){if(pickDirty)drawPick();const r=cv.getBoundingClientRect(),x=Math.round(e.clientX-r.left),y=Math.round(e.clientY-r.top);
  if(x<0||y<0||x>=W||y>=H){tip.style.opacity=0;return;}
  const px=pctx.getImageData(x,y,1,1).data,id=(px[0]<<16)|(px[1]<<8)|px[2];
  if(id<=0||id>hexes.length){tip.style.opacity=0;return;}
  const h=hexes[id-1];
  let biz='';
  if(h.lead>=0){const ms=[];for(let i=0;i<CATS.length;i++) if((h.mask>>i)&1) ms.push(i);
    biz='<div class="mi">missing</div>'+ms.map(i=>`<span class="biz" style="background:${catColor(i)}">${LABELS[i]}</span>`).join('');}
  else biz='<div class="mi" style="color:var(--muted)">no conspicuous gap</div>';
  tip.innerHTML=`<div class="nb">${DATA.ntas[h.nta]}</div><div class="pop">${h.pop.toLocaleString()} residents</div>${biz}`;
  tip.style.left=Math.min(x+16,W-230)+'px';tip.style.top=Math.min(y+14,H-90)+'px';tip.style.opacity=1;}

// build the filter list
const order=Object.entries(DATA.gapCounts).filter(([,n])=>n>0).sort((a,b)=>b[1]-a[1]);
const opts=document.getElementById('opts');
function mkOpt(label,color,count,val){
  const b=document.createElement('button');b.className='opt';b.setAttribute('aria-pressed',val===filter);
  b.innerHTML=`<span class="sw" style="background:${color}"></span><span>${label}</span><span class="n">${count.toLocaleString()}</span>`;
  b.onclick=()=>{filter=val;[...opts.children].forEach(c=>c.setAttribute('aria-pressed','false'));b.setAttribute('aria-pressed','true');update();};
  opts.appendChild(b);}
mkOpt('All gaps','linear-gradient(90deg,#b5541f,#2f7d5c,#3d6fb4)',DATA.nGap,-1);
for(const [cat,n] of order){ mkOpt(LABELS[CATS.indexOf(cat)], COLORS[cat], n, CATS.indexOf(cat)); }
function update(){
  // stat: areas + residents under filter
  let n=0,pop=0; for(const h of hexes) if(shown(h)){n++;pop+=h.pop;}
  document.getElementById('s-n').textContent=n.toLocaleString();
  document.getElementById('s-l').textContent = (filter<0?'areas with a gap':'areas missing '+LABELS[filter].toLowerCase())+
     ` · ${(pop/1000).toFixed(0)}k residents`;
  redraw();
}
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',redraw);
new MutationObserver(redraw).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
addEventListener('resize',resize);
resize(); update();
</script>
"""
(sp/"gap_map.html").write_text(HTML.replace("__DATA__", data))
print("wrote gap_map.html", len(HTML.replace("__DATA__",data))//1024, "KB")
