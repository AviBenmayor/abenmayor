const http=require('http'),https=require('https'),fs=require('fs'),path=require('path'),zlib=require('zlib');
const port=process.env.PORT||8080, dir=__dirname, GKEY=process.env.GOOGLE_PLACES_KEY||'';
const T={'.html':'text/html','.json':'application/json','.js':'text/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml'};
// category -> Google Places (New) Table A types
const GT={grocery:['grocery_store','supermarket'],convenience:['convenience_store'],pharmacy:['pharmacy','drugstore'],
  laundry:['laundry'],hair_barber:['hair_salon','barber_shop'],nails_beauty:['nail_salon','beauty_salon'],
  restaurant:['restaurant'],cafe_bakery:['cafe','bakery','coffee_shop'],bar:['bar','pub'],
  childcare:['child_care_agency'],clinic:['doctor'],fitness:['gym'],bank:['bank'],hardware:['hardware_store'],tailor_repair:['tailor']};
// global rate limit (protect the key on a public URL): ~30/min
let tok=30, last=Date.now();
function allow(){const now=Date.now();tok=Math.min(30,tok+(now-last)/1000*0.5);last=now;if(tok>=1){tok-=1;return true;}return false;}

function googleNearby(lat,lng,cat){return new Promise((resolve)=>{
  const types=GT[cat]; if(!types||!GKEY)return resolve({error:'unavailable'});
  const body=JSON.stringify({includedTypes:types,maxResultCount:20,
    locationRestriction:{circle:{center:{latitude:lat,longitude:lng},radius:800}}});
  const req=https.request({hostname:'places.googleapis.com',path:'/v1/places:searchNearby',method:'POST',
    headers:{'Content-Type':'application/json','X-Goog-Api-Key':GKEY,'X-Goog-FieldMask':'places.displayName,places.location'}},
    r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>{try{const j=JSON.parse(d);const places=j.places||[];
      resolve({n:places.length,names:places.slice(0,6).map(p=>(p.displayName||{}).text||'?')});}catch(e){resolve({error:'parse'});}});});
  req.on('error',()=>resolve({error:'net'}));req.write(body);req.end();
});}

http.createServer(async(req,res)=>{
  const u=new URL(req.url,'http://x'); const p0=u.pathname;
  if(p0==='/api/validate'){
    if(!allow()){res.writeHead(429);return res.end('{"error":"rate"}');}
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
}).listen(port,()=>console.log('loci webmap+validate on :'+port));
