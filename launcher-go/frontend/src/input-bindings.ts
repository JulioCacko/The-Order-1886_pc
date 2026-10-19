export function withBinding(current:unknown,button:string,source:string):Record<string,string>{
 const mapping=current&&typeof current==='object'&&!Array.isArray(current)?{...current} as Record<string,string>:{};
 if(source) mapping[button]=source;
 else delete mapping[button];
 return mapping;
}
