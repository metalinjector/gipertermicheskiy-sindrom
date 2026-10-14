const {Resvg}=require('@resvg/resvg-js');
const fs=require('fs');
const [,, inp, out, widthArg] = process.argv;
const svg=fs.readFileSync(inp,'utf8');
const opts={fitTo:{mode:'width',value:parseInt(widthArg||'2400')}, font:{fontFiles:['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'], loadSystemFonts:true, defaultFontFamily:'DejaVu Sans'}, background:'#ffffff'};
const r=new Resvg(svg,opts);
const png=r.render().asPng();
fs.writeFileSync(out,png);
console.log(out, r.width, r.height);
