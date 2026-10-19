export function createSettingsSaver(read:(key:string)=>unknown,write:(key:string,value:unknown)=>Promise<void>){
 let pending=Promise.resolve();
 return (key:string,update:unknown)=>{
  const operation=pending.then(()=>write(key,typeof update==='function'?update(read(key)):update));
  pending=operation.catch(()=>{});
  return operation;
 };
}
