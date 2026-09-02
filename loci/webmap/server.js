const http=require('http'),fs=require('fs'),path=require('path');
const port=process.env.PORT||8080, dir=__dirname;
const T={'.html':'text/html','.json':'application/json','.geojson':'application/json','.js':'text/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml'};
http.createServer((req,res)=>{
  let p=decodeURIComponent((req.url||'/').split('?')[0]); if(p==='/')p='/index.html';
  const fp=path.normalize(path.join(dir,p));
  if(!fp.startsWith(dir)){res.writeHead(403);return res.end('forbidden');}
  fs.readFile(fp,(e,data)=>{ if(e){res.writeHead(404);return res.end('not found');}
    res.writeHead(200,{'Content-Type':T[path.extname(fp)]||'application/octet-stream','Cache-Control':'public,max-age=300'});
    res.end(data);});
}).listen(port,()=>console.log('loci webmap on :'+port));
