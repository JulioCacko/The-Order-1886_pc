import {copyFileSync, mkdirSync} from 'node:fs';
const source = new URL('../../../launcher/order1886/', import.meta.url);
const target = new URL('../public/assets/', import.meta.url);
mkdirSync(target, {recursive:true});
for (const name of ['launcher-art.jpg','logo-horizontal.png','logo-stacked.png']) {
  copyFileSync(new URL(name,source), new URL(name,target));
}
const build = new URL('../../build/',import.meta.url);
mkdirSync(build,{recursive:true});
copyFileSync(new URL('app-icon.png',source),new URL('appicon.png',build));

