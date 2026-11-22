#!/usr/bin/env python3
"""Run LTspice serially and retain input hashes and simulator outputs."""
from pathlib import Path
import os,sys,json,time,hashlib,subprocess,argparse,fcntl
ROOT=Path(__file__).resolve().parents[1]
RUNNER=os.environ.get('LTSPICE_RUNNER','/Applications/LTspice.app/Contents/SharedSupport/ltspice/LTspice/run_ltspice')
BASE=dict(vc=1.50,cc=.3,bias=1,cl=1,g1=4,g2=8,scale=1,rin=10000,amp=.04,freq=1e6,vdd=1.8,vcm=.9,tdeg=27,dt=2,stop=40,kf=1e-25,ppd=120)

def deck(kind='ac',sweep=None,values=None,**kw):
    p={**BASE,**kw}
    s='* CMOS VGA simulation with generic Level-1 MOS models.\n'
    s+='.param '+' '.join(f'{k}={v}' for k,v in p.items())+'\n.param KFL={kf}\n'
    s+='''.include ../../models/vga.lib
.options plotwinsize=0 numdgt=15 reltol=1e-5 abstol=1e-13 vntol=1e-8 chgtol=1e-20 trtol=1 method=trap
.temp {tdeg}
VDD VDD 0 {vdd}
VREF REF 0 {vcm}
VIN VIN 0 SINE({vcm} {amp/2} {freq}) AC 1
VC CTRL 0 {vc}
* Complementary control-gate driver is behavioural, no power/noise claim.
BCP CP 0 V=V(VDD)-V(CTRL)
XG VIN OUT CTRL CP REF VDD 0 VGA CC={cc*1p} BIAS={bias} CL={cl*1p} G1={g1} G2={g2} SCALE={scale} RIN={rin}
'''
    if sweep:s+=f'.step param {sweep} list '+ ' '.join(str(v) for v in values)+'\n'
    if kind=='op':s+='.options logopinfo\n.op\n'
    elif kind=='ac':s+='.ac dec {ppd} 10 1G\n.save V(OUT) V(VIN) V(xg:att) V(xg:mid) I(VIN)\n'
    elif kind=='noise':s+='.noise V(OUT) VIN dec {ppd} 10 1G\n'
    else:s+='.tran 0 {stop*1u} 0 {dt*1n}\n.save V(OUT) V(VIN) V(CTRL) V(xg:att) V(xg:mid) I(VDD) I(VREF) I(VC) I(BCP)\n'
    return s+'.end\n'

def execute(name,content,force=False,timeout=160):
    folder=ROOT/'runs'/name;folder.mkdir(parents=True,exist_ok=True)
    path=folder/'test.cir';meta=folder/'run.json'
    model=''.join(p.read_text() for p in sorted((ROOT/'models').glob('*.lib')))
    sha=hashlib.sha256((content+model).encode()).hexdigest()
    if meta.exists() and not force:
        m=json.loads(meta.read_text())
        if m.get('success') and m.get('sha256')==sha and path.with_suffix('.raw').exists():print('CACHED',name,flush=True);return
    if meta.exists():
        archive=ROOT/('superseded_runs' if json.loads(meta.read_text()).get('success') else 'failed_runs');archive.mkdir(exist_ok=True)
        folder.rename(archive/f'{name}_{int(time.time())}')
        folder.mkdir(exist_ok=True)
    path.write_text(content)
    start=time.time();command=[RUNNER,'-b','-ascii',path.name]
    env={**os.environ,'MVK_CONFIG_LOG_LEVEL':'0','WINEDEBUG':'-all'}
    try:
        with (ROOT/'.ltspice_serial.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            r=subprocess.run(command,cwd=folder,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
        output=r.stdout;code=r.returncode
    except subprocess.TimeoutExpired as ex:output=ex.stdout or b'';code=124
    (folder/'runner.log').write_bytes(output)
    log=path.with_suffix('.log').read_text(errors='replace') if path.with_suffix('.log').exists() else ''
    ok=code==0 and path.with_suffix('.raw').exists() and 'Total elapsed time' in log
    meta.write_text(json.dumps(dict(run_id=name,command=command,sha256=sha,success=ok,returncode=code,wall_s=time.time()-start,model='models/vga.lib'),indent=2))
    print('FINISHED' if ok else 'FAILED',name,round(time.time()-start,2),flush=True)
    if not ok:raise RuntimeError(log[-1600:]+'\n'+output[-1200:].decode(errors='replace'))

def experiments():
    tests=dict(v1_op=deck('op'),v1_gain=deck(sweep='vc',values=[1.475,1.48,1.49,1.50,1.52,1.55,1.6,1.7,1.8]),v1_tran=deck('tran'),v1_noise=deck('noise'))
    tests['comp_ac']=deck(sweep='cc',values=[.3,.6,1,2],vc=1.49)
    tests['comp_tran']=deck('tran',sweep='cc',values=[.3,.6,1,2],vc=1.49,amp=.4/11.1464)
    tests['comp_step']=deck('tran',sweep='cc',values=[.3,.6,1,2],vc=1.49,stop=5,dt=.2).replace('SINE({vcm} {amp/2} {freq}) AC 1','PULSE({vcm} {vcm+.005} 1u 1n 1n 2u 5u) AC 1')
    tests['v2_gain_dense']=deck(sweep='vc',values=[round(1.47+i*.002,6) for i in range(166)],cc=1,ppd=80)
    tests['v2_noise']=deck('noise',sweep='vc',values=[1.48,1.5,1.6,1.8],cc=1)
    tests['v3_gain']=deck(sweep='vc',values=[1.48,1.49,1.5,1.55,1.6,1.8],cc=1,g1=8,g2=8,scale=4,rin=5000)
    tests['v3_tran']=deck('tran',sweep='vc',values=[1.48,1.49,1.5],cc=1,g1=8,g2=8,scale=4,rin=5000,amp=.04)
    tests['v3_noise']=deck('noise',sweep='vc',values=[1.48,1.5,1.6,1.8],cc=1,g1=8,g2=8,scale=4,rin=5000)
    tests['gain_calibration']=deck(sweep='vc',values=[round(1.48+i*.001,6) for i in range(321)],cc=1,g1=8,g2=8,scale=4,rin=5000,ppd=80)
    return tests

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('names',nargs='*');ap.add_argument('--force',action='store_true');a=ap.parse_args();tests=experiments()
    for name in a.names or tests:execute(name,tests[name],a.force)
