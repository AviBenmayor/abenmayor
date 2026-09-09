const http=require('http'),https=require('https'),fs=require('fs'),path=require('path'),zlib=require('zlib');
const port=process.env.PORT||8080, dir=__dirname, GKEY=process.env.GOOGLE_PLACES_KEY||'';
const T={'.html':'text/html','.json':'application/json','.js':'text/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml'};
// category -> Google Places (New) Table A types. Mirrors google_places.py's
// GOOGLE_TYPES (source of truth; see tests/test_google_types_drift.py, GTM-105
// finding F). GTM-105 2026-09-08 audit, ranked item 4, owner-approved: clinic
// removed entirely (doctor/medical_lab measure a different universe than the
// 621111/621493 anchor -- GT[cat] being undefined already resolves to
// {error:'unavailable'} above, so no code change needed for the missing key).
// tailor_repair kept as `tailor` only -- not usable for headline claims,
// nothing better exists in Table A.
const GT={grocery:['grocery_store','supermarket'],convenience:['convenience_store'],pharmacy:['pharmacy','drugstore'],
  laundry:['laundry'],hair_barber:['hair_salon','barber_shop','hair_care','beauty_salon'],nails_beauty:['nail_salon'],
  restaurant:['restaurant','fast_food_restaurant','meal_takeaway','bar_and_grill',
    'american_restaurant','chinese_restaurant','italian_restaurant','japanese_restaurant',
    'mexican_restaurant','indian_restaurant','thai_restaurant','korean_restaurant',
    'vietnamese_restaurant','greek_restaurant','french_restaurant','spanish_restaurant',
    'turkish_restaurant','lebanese_restaurant','middle_eastern_restaurant',
    'mediterranean_restaurant','brazilian_restaurant','ramen_restaurant','sushi_restaurant',
    'pizza_restaurant','seafood_restaurant','steak_house','hamburger_restaurant',
    'sandwich_shop','vegan_restaurant','vegetarian_restaurant','breakfast_restaurant',
    'brunch_restaurant','barbecue_restaurant','indonesian_restaurant','african_restaurant',
    'afghani_restaurant','asian_restaurant','buffet_restaurant','fine_dining_restaurant'],
  cafe_bakery:['cafe','coffee_shop','bakery','donut_shop','bagel_shop','ice_cream_shop','juice_shop','dessert_shop','tea_house'],
  bar:['bar','pub','wine_bar','night_club'],
  childcare:['child_care_agency','preschool'],fitness:['gym','fitness_center','yoga_studio','sports_club'],bank:['bank'],hardware:['hardware_store'],tailor_repair:['tailor']};
// Spend guard for a PUBLIC url. Two layers:
//  1. hard total cap per process: GOOGLE_CLICK_BUDGET calls, default 0 = per-click validation OFF.
//     The coverage check now runs as a capped, stratified batch (`loci validate`), not per click.
//  2. rate limit ~30/min on top, so a burst can't drain the cap in seconds.
const CLICK_BUDGET=parseInt(process.env.GOOGLE_CLICK_BUDGET||'0',10); let clicks=0;
let tok=30, last=Date.now();
function allow(){if(!(CLICK_BUDGET>0)||clicks>=CLICK_BUDGET)return false;const now=Date.now();tok=Math.min(30,tok+(now-last)/1000*0.5);last=now;if(tok>=1){tok-=1;clicks+=1;return true;}return false;}

// includedPrimaryTypes, not includedTypes: loci is single-label per place, so
// matching on the full multi-label `types` array double counts a place across
// every category one of its secondary types happens to hit (GTM-105 finding A).
// Radius: the screen's 800 m NETWORK threshold / measured NYC circuity (D53) —
// read from src/loci/reach_tiers.yaml `validation.derived_radius_m` so the map's
// check uses the same disc as `loci validate` (tests/test_validation_radius.py).
const RADIUS_M=(()=>{try{const y=fs.readFileSync(path.join(__dirname,'..','src','loci','reach_tiers.yaml'),'utf8');
  const m=y.match(/^\s*derived_radius_m:\s*(\d+)/m); if(m)return parseInt(m[1],10);}catch(e){}
  throw new Error('reach_tiers.yaml validation.derived_radius_m not found');})();
function googleNearby(lat,lng,cat){return new Promise((resolve)=>{
  const types=GT[cat]; if(!types||!GKEY)return resolve({error:'unavailable'});
  const body=JSON.stringify({includedPrimaryTypes:types,maxResultCount:20,
    locationRestriction:{circle:{center:{latitude:lat,longitude:lng},radius:RADIUS_M}}});
  const req=https.request({hostname:'places.googleapis.com',path:'/v1/places:searchNearby',method:'POST',
    headers:{'Content-Type':'application/json','X-Goog-Api-Key':GKEY,'X-Goog-FieldMask':'places.displayName,places.location'}},
    r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>{try{const j=JSON.parse(d);const places=j.places||[];
      resolve({n:places.length,names:places.slice(0,6).map(p=>(p.displayName||{}).text||'?')});}catch(e){resolve({error:'parse'});}});});
  req.on('error',()=>resolve({error:'net'}));req.write(body);req.end();
});}

http.createServer(async(req,res)=>{
  const u=new URL(req.url,'http://x'); const p0=u.pathname;
  if(p0==='/api/validate'){
    if(!allow()){res.writeHead(CLICK_BUDGET>0&&clicks<CLICK_BUDGET?429:503);return res.end(JSON.stringify({error:CLICK_BUDGET>0?(clicks>=CLICK_BUDGET?'budget':'rate'):'disabled'}));}
    const lat=parseFloat(u.searchParams.get('lat')),lng=parseFloat(u.searchParams.get('lng')),cat=u.searchParams.get('cat');
    if(!isFinite(lat)||!isFinite(lng)||!cat){res.writeHead(400);return res.end('{"error":"bad"}');}
    const out=await googleNearby(lat,lng,cat);
    res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});return res.end(JSON.stringify(out));
  }
  let p=decodeURIComponent(p0); if(p==='/')p='/index.html';
  const fp=path.normalize(path.join(dir,p));
  if(!fp.startsWith(dir)){res.writeHead(403);return res.end('forbidden');}
  fs.readFile(fp,(e,data)=>{if(e){res.writeHead(404);return res.end('not found');}
    const ct=T[path.extname(fp)]||'application/octet-stream', ae=req.headers['accept-encoding']||'';
    if(/gzip/.test(ae)&&data.length>2048){res.writeHead(200,{'Content-Type':ct,'Content-Encoding':'gzip','Cache-Control':'public,max-age=300'});res.end(zlib.gzipSync(data));}
    else{res.writeHead(200,{'Content-Type':ct,'Cache-Control':'public,max-age=300'});res.end(data);}});
}).listen(port,()=>console.log('loci webmap on :'+port+' (per-click Google validation '+(CLICK_BUDGET>0?'capped at '+CLICK_BUDGET:'OFF')+')'));
