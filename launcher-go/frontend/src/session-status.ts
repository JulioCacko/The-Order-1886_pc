export function completionNotice(data: unknown, logfile: string): {message:string;failed:boolean} {
  if(!Array.isArray(data)||typeof data[0]!=='number'||!Number.isInteger(data[0])) {
    return {message:'The backend ended without a valid exit status.',failed:true};
  }
  const [code,mode,cancelled]=data;
  if(code===130) return {message:'Session stopped.',failed:false};
  if(code!==0) return {message:`Session failed (exit ${code}). Log: ${logfile||'Open player data to inspect the session logs.'}`,failed:true};
  if(cancelled===true) return {message:'Session stopped.',failed:false};
  return {message:mode==='verify'?'Verification completed.':mode==='prepare'?'Preparation completed.':'Session ended.',failed:false};
}

