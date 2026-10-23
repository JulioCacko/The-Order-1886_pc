export type EarnedTrophy={id:number;unlocked_at:number};
export type TrophyArtwork={id:number;icon:string;name?:string;detail?:string;grade?:string;hidden?:boolean};

export function achievementRows(earned:EarnedTrophy[],catalog:TrophyArtwork[]=[]){
 const rows=new Map(catalog.map(item=>[item.id,{...item,unlocked_at:undefined as number|undefined}]));
 for(const item of earned) rows.set(item.id,{...rows.get(item.id),id:item.id,icon:rows.get(item.id)?.icon??'',unlocked_at:item.unlocked_at});
 return [...rows.values()].sort((a,b)=>a.id-b.id);
}

export function unlockDate(stamp:number,language:string){
 if(!Number.isSafeInteger(stamp)||stamp<=0||stamp>8640000000000) return null;
 const locales:Record<string,string>={en:'en',ru:'ru',ar:'ar',es:'es',pt:'pt-BR',fr:'fr',de:'de',it:'it',pl:'pl',tr:'tr',zh:'zh-Hans',ja:'ja',ko:'ko'};
 const date=new Date(stamp*1000);
 return {iso:date.toISOString(),text:new Intl.DateTimeFormat(locales[language]??'en',{dateStyle:'medium',timeStyle:'short'}).format(date)};
}
