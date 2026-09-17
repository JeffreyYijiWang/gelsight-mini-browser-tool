import http from 'node:http';
import path from 'node:path';
import {readdir,stat,readFile,writeFile} from 'node:fs/promises';
import {chromium} from 'playwright';
const base=path.resolve('test-artifacts/example-data/exports');
const galleries=await Promise.all((await readdir(base)).filter(n=>n.startsWith('gallery-')).map(async n=>({root:path.join(base,n),time:(await stat(path.join(base,n))).mtimeMs})));
galleries.sort((a,b)=>b.time-a.time);if(!galleries[0])throw new Error('Generate examples first.');
const roots={gallery:galleries[0].root,dictionary:path.resolve('texture-dictionary/dist')};
const types={'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json','.png':'image/png','.webp':'image/webp'};
const server=http.createServer(async(req,res)=>{try{const parts=decodeURIComponent(new URL(req.url,'http://localhost').pathname).split('/').filter(Boolean);const root=roots[parts.shift()];if(!root){res.writeHead(404).end();return;}let file=path.resolve(root,...parts);if(!file.startsWith(root+path.sep)&&file!==root)throw new Error('outside');if((await stat(file)).isDirectory())file=path.join(file,'index.html');res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream'});res.end(await readFile(file));}catch{res.writeHead(404).end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const page=await browser.newPage({viewport:{width:1440,height:960}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
const report={};
try{
 await page.goto(origin+'/gallery/',{waitUntil:'networkidle'});await page.getByRole('button',{name:'Inspect material sphere'}).click();await page.locator('canvas.webgl').waitFor();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Actual displaced'));
 await page.screenshot({path:'test-artifacts/standalone-gallery.png'});report.standalone_gallery=true;
 await page.goto(origin+'/dictionary/',{waitUntil:'networkidle'});await page.getByText('No specimens here yet.',{exact:true}).waitFor();
 report.public_entries=(await(await page.request.get(origin+'/dictionary/collection.json')).json()).entries.length;
 await page.screenshot({path:'test-artifacts/public-empty-dictionary.png'});
 await page.getByRole('link',{name:'About / Process',exact:true}).click();await page.reload({waitUntil:'networkidle'});report.about_direct_refresh=await page.title();
 await page.getByRole('link',{name:'Compare',exact:true}).click();await page.getByText('Select at least two specimens.',{exact:true}).waitFor();
 report.subdirectory_routes=true;report.page_errors=errors;if(errors.length||report.public_entries)throw new Error(JSON.stringify(report));report.passed=true;
}catch(error){report.passed=false;report.error=error.stack;process.exitCode=1;}
finally{await writeFile('test-artifacts/static-export-report.json',JSON.stringify(report,null,2));console.log(report);await browser.close();await new Promise(r=>server.close(r));}
