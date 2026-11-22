#!/usr/bin/env python3
"""Run the fixed VGA protocol with LTspice.

Runs are cached by deck/model hash; source and model files are read-only.
"""
from pathlib import Path
import sys,json,csv,hashlib,subprocess,os,time,fcntl,argparse,shutil
import numpy as np
from scipy.interpolate import PchipInterpolator
ROOT=Path(__file__).resolve().parent
HELPERS=ROOT/'helpers'
sys.path.insert(0,str(HELPERS))
import run as oldrun
from measure import raw,ac,harmonics,interp
P=json.loads((ROOT.parent/'protocol.json').read_text())['vga']
OUT=ROOT/'results';OUT.mkdir(exist_ok=True)
for d in ['models','runs','figures']: (ROOT/d).mkdir(exist_ok=True)
LOCK=Path(os.environ.get('LTSPICE_LOCK', str(ROOT.parent/'.ltspice_serial.lock')))
RUNNER=os.environ.get('LTSPICE_RUNNER','/Applications/LTspice.app/Contents/SharedSupport/ltspice/LTspice/run_ltspice')
TARGET=P['target_output_vpp']
CONDS={}

def dump(name,obj):
    (OUT/name).write_text(json.dumps(obj,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)))

def table(name,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def execute(name,content,condition=None):
    folder=ROOT/'runs'/name;folder.mkdir(exist_ok=True)
    meta=folder/'run.json';path=folder/'test.cir'
    model=''.join(p.read_text() for p in sorted((ROOT/'models').glob('*.lib')))
    digest=hashlib.sha256((content+model).encode()).hexdigest()
    CONDS[name]=condition or {}
    if meta.exists():
        old=json.loads(meta.read_text())
        if old.get('success') and old.get('sha256')==digest:
            print('CACHED',name,flush=True);return raw(path.with_suffix('.raw'))
        dest=ROOT/'superseded_runs';dest.mkdir(exist_ok=True)
        folder.rename(dest/f'{name}_{time.time_ns()}');folder.mkdir()
    path.write_text(content)
    start=time.time()
    cmd=[RUNNER,'-b','-ascii',path.name]
    try:
        with LOCK.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            p=subprocess.run(cmd,cwd=folder,env={**os.environ,'WINEDEBUG':'-all','MVK_CONFIG_LOG_LEVEL':'0'},capture_output=True,timeout=300)
        code=p.returncode;output=p.stdout+p.stderr
    except subprocess.TimeoutExpired as ex:code=124;output=(ex.stdout or b'')+(ex.stderr or b'')
    (folder/'runner.log').write_bytes(output)
    log=path.with_suffix('.log').read_text(errors='replace') if path.with_suffix('.log').exists() else ''
    success=code==0 and path.with_suffix('.raw').exists() and 'Total elapsed time' in log
    meta.write_text(json.dumps(dict(success=success,sha256=digest,returncode=code,wall_s=time.time()-start,command=cmd,conditions=condition),indent=2))
    print('FINISHED' if success else 'FAILED',name,round(time.time()-start,2),flush=True)
    if not success:raise RuntimeError(output[-1800:].decode(errors='replace')+'\n'+log[-1800:])
    return raw(path.with_suffix('.raw'))

def final(stage,kind='ac',**kw):
    return oldrun.deck(kind,**dict(cc=1,g1=stage[0],g2=stage[1],scale=4,rin=5000,**kw)).replace('.end','CDET OUT SENSE 10p\nRDET SENSE 0 1Meg\n.end')

def cases(stage,kind,rows,**kw):
    keys=sorted(set().union(*(r.keys() for r in rows)))
    params={key:'{table(testcase,'+','.join(f'{i},{r.get(key,kw.get(key,oldrun.BASE.get(key)))}' for i,r in enumerate(rows))+')}' for key in keys}
    return final(stage,kind,**{**kw,**params}).replace('.end',f'.step param testcase 0 {len(rows)-1} 1\n.end')

def stage_study():
    output=[]
    for stage in P['fixed_stage_candidates']:
        tag=f'stage{stage[0]}x{stage[1]}'
        vcs=np.round(np.arange(321)*.001+1.48,6)
        deck=final(stage,sweep='vc',values=vcs,ppd=100).replace('.ac dec {ppd} 10 1G','.ac lin 1 1Meg 1Meg')
        # A single-frequency stepped raw has equal frequency axes: separate by row explicitly.
        rr=execute(tag+'_cal',deck,dict(stage=stage,vc=list(vcs),frequency_Hz=1e6))
        if len(rr)==1 and len(rr[0]['v(out)'])==len(vcs): gains=np.abs(rr[0]['v(out)'])
        else:gains=np.array([abs(x['v(out)'][0]) for x in rr])
        assert len(gains)==len(vcs) and np.all(np.diff(gains)<0)
        if gains[-1]>1 or gains[0]<16:raise RuntimeError(f'{tag}: coverage fails {gains[-1]}..{gains[0]}')
        fn=PchipInterpolator(gains[::-1],vcs[::-1])
        points=[dict(target_gain=g,vc=float(fn(g))) for g in P['calibrated_gains']]
        dump(tag+'_calibration.json',[dict(vc=float(v),gain=float(g)) for v,g in zip(vcs,gains)])
        dump(tag+'_points.json',points)
        rrac=execute(tag+'_ac',cases(stage,'ac',[dict(vc=p['vc']) for p in points],ppd=160),dict(stage=stage,points=points))
        rrtran=execute(tag+'_tran',cases(stage,'tran',[dict(vc=p['vc'],amp=TARGET/p['target_gain']) for p in points],stop=40,dt=2),dict(stage=stage,output_target_Vpp=TARGET,points=points))
        rows=[]
        for j,(p,a,t) in enumerate(zip(points,rrac,rrtran)):
            aa=ac(a);h=harmonics(t);hin=harmonics(t,node='v(vin)');gain=h['fundamental_pp_V']/hin['fundamental_pp_V']
            dev=100*(gain/aa['gain_1M']-1)
            rows.append(dict(stage=tag,step=j,**p,**aa,output_Vpp=h['vpp_V'],fundamental_Vpp=h['fundamental_pp_V'],THD_pct=h['THD_pct'],gain_deviation_pct=dev,passes=bool(abs(dev)<=1 and h['THD_pct']<=1 and aa['bandwidth_MHz']>=5 and aa['peaking_dB']<=.5),provenance='SIMULATED'))
        table(tag+'_metrics.csv',rows);output.append(dict(stage=stage,tag=tag,rows=rows,all_pass=all(r['passes'] for r in rows),worst_THD_pct=max(r['THD_pct'] for r in rows)))
    passing=[s for s in output if s['all_pass']]
    chosen=min(passing,key=lambda s:s['worst_THD_pct']) if passing else None
    summary=dict(candidates=output,selected_stage=chosen['stage'] if chosen else None,selection_protocol=P['stage_selection'])
    dump('stage_selection.json',summary)
    print('STAGE_SELECTION',json.dumps(summary),flush=True)
    return chosen

def agc(stage,points,amp=.1,ki=87000,dt=5,stop=300,transition=None):
    lo=points[-1]['vc'];hi=points[0]['vc']
    s=final(stage,'tran',amp=amp,dt=dt,stop=stop)
    s=s.replace('VC CTRL 0 {vc}',f'''.param ki={ki} tauenv=1 vlo={lo:.12g} vhi={hi:.12g}
CCTRL CTRL 0 1n
RCTRL CTRL 0 1T
BINT 0 CTRL I=ki*1n*(max(V(ENV)-{TARGET}/pi,0)*limit((vhi-V(CTRL))/1m,0,1)+min(V(ENV)-{TARGET}/pi,0)*limit((V(CTRL)-vlo)/1m,0,1))+1m*(max(vlo-V(CTRL),0)-max(V(CTRL)-vhi,0))
.ic V(CTRL)=1.55
BABS RECT 0 V=abs(V(SENSE))
RENV RECT ENV 1k
CENV ENV 0 {{tauenv*1n}}
''')
    s=s.replace('V(CTRL) V(xg:att)','V(CTRL) V(ENV) V(SENSE) V(xg:att)').replace('I(VC) I(BCP)','I(BCP)')
    if transition:
        before,after,at=transition
        s=s.replace('VIN VIN 0 SINE({vcm} {amp/2} {freq}) AC 1',f'BINPUT VIN 0 V={{vcm+({before}+({after-before})*limit((time-{at}u)/20n,0,1))/2*sin(2*pi*freq*time)}}')
    return s

def cyc_metrics(r,name,amp,ki,transition=None):
    t=r['time'].real;y=r['v(out)'].real;ctrl=r['v(ctrl)'].real;n=int(np.floor(t[-1]*1e6+1e-5));cy=[]
    for k in range(n):
        tu=(k+np.arange(501)/500)*1e-6;yy=np.interp(tu,t,y);vv=np.interp(tu,t,ctrl)
        cy.append(dict(cycle=k,end_us=k+1,output_Vpp=float(np.ptp(yy)),control_ripple_mV=float(np.ptp(vv)*1e3),vout_min=float(yy.min()),vout_max=float(yy.max())))
    last=cy[-20:];mask=t>=t[-1]-20e-6;h=harmonics(r);actual=amp if transition is None else transition[1]
    tu=np.linspace(t[-1]-20e-6,t[-1],20001)
    def mean(node):return float(np.trapezoid(np.interp(tu,t,r[node].real),tu)/(tu[-1]-tu[0]))
    m=dict(run=name,input_Vpp=actual,ki_per_s=ki,output_Vpp=float(np.mean([x['output_Vpp'] for x in last])),THD_pct=float(h['THD_pct']),control_mean_V=mean('v(ctrl)'),control_ripple_mV=float(np.ptp(ctrl[mask])*1e3),power_core_mW=-1.8*mean('i(vdd)')*1e3,provenance='SIMULATED; time-weighted power calculated from simulated supply current')
    m['amplitude_error_pct']=100*(m['output_Vpp']/TARGET-1)
    if transition:
        ev=transition[2];post=cy[int(ev):];ok=np.array([abs(x['output_Vpp']/TARGET-1)<=.05 for x in post]);remain=np.logical_and.accumulate(ok[::-1])[::-1];inds=np.flatnonzero(remain&(np.arange(len(post))<=len(post)-21))
        m.update(before_Vpp=transition[0],after_Vpp=transition[1],settling_us=float(post[inds[0]]['end_us']-ev) if len(inds) else None,observed_post_us=len(post),overshoot_pct=max(0,max(x['output_Vpp'] for x in post)/TARGET-1)*100,undershoot_pct=max(0,1-min(x['output_Vpp'] for x in post)/TARGET)*100,post_min_V=min(x['vout_min'] for x in post),post_max_V=max(x['vout_max'] for x in post))
    table(name+'_cycles.csv',cy)
    return m

def controller_study(chosen):
    stage=chosen['stage'];tag=chosen['tag'];points=json.loads((OUT/(tag+'_points.json')).read_text())
    stat=[];dynamic=[]
    for ki in P['integral_strengths_per_s']:
        for a in P['static_input_vpp']:
            name=f'static_k{ki}_a{round(a*1000)}';rr=execute(name,agc(stage,points,amp=a,ki=ki),dict(stage=stage,amp=a,ki=ki,target=TARGET));stat.append(cyc_metrics(rr[0],name,a,ki))
        for a,b in [(P['static_input_vpp'][0],P['static_input_vpp'][-1]),(P['static_input_vpp'][-1],P['static_input_vpp'][0])]:
            name=f'dynamic_k{ki}_{round(a*1000)}to{round(b*1000)}';tr=(a,b,200)
            rr=execute(name,agc(stage,points,amp=a,ki=ki,stop=500,transition=tr),dict(stage=stage,transition=tr,ki=ki,target=TARGET));dynamic.append(cyc_metrics(rr[0],name,a,ki,tr))
        table('agc_static.csv',stat);table('agc_dynamic.csv',dynamic)
    choices=[]
    for ki in P['integral_strengths_per_s']:
        ss=[r for r in stat if r['ki_per_s']==ki];dd=[r for r in dynamic if r['ki_per_s']==ki];weak=min(ss,key=lambda r:r['input_Vpp'])
        passed=all(abs(r['amplitude_error_pct'])<=5 for r in ss) and weak['control_ripple_mV']<=.1 and all(r['settling_us'] is not None for r in dd)
        choices.append(dict(ki_per_s=ki,passes=bool(passed),weak_control_ripple_mV=weak['control_ripple_mV'],worst_recovery_us=max(r['settling_us'] or float('inf') for r in dd)))
    passing=[c for c in choices if c['passes']];winner=min(passing,key=lambda c:c['worst_recovery_us']) if passing else None
    dump('controller_selection.json',dict(candidates=choices,selected=winner,static=stat,dynamic=dynamic,selection_protocol=P['controller_selection']))
    print('CONTROLLER_SELECTION',json.dumps(choices),flush=True)
    return winner

def validation(chosen,control):
    stage=chosen['stage'];tag=chosen['tag'];points=json.loads((OUT/(tag+'_points.json')).read_text());rows=[]
    pts=[points[2],points[-1]]
    for p in pts:
        g=p['target_gain'];vc=p['vc'];name=f'selected_op_g{g}';r=execute(name,final(stage,'op',vc=vc),dict(stage=stage,gain=g))[0]
        rows.append(dict(gain=g,control_V=vc,output_bias_V=float(r['v(out)'][0].real),supply_current_mA=-float(r['i(vdd)'][0].real)*1e3,core_power_mW=-1.8*float(r['i(vdd)'][0].real)*1e3,scope='1.8V analogue core incl. bias; excludes ideal reference and behavioural controller implementation'))
    table('operating_point.csv',rows)
    rs=execute('selected_noise',cases(stage,'noise',[dict(vc=p['vc']) for p in pts],ppd=180),dict(stage=stage,points=pts))
    noise=[]
    for p,r in zip(pts,rs):
        f=r['frequency'].real;out=r['v(onoise)'].real;inp=r['v(inoise)'].real
        noise.append(dict(gain=p['target_gain'],output_nV_sqrtHz_100k=float(interp(f,out,1e5)*1e9),input_nV_sqrtHz_100k=float(interp(f,inp,1e5)*1e9),scope='fixed-control DC small-signal, assumed model; excludes behavioural AGC implementation noise'))
        table(f'noise_g{p["target_gain"]}.csv',[dict(frequency_Hz=float(x),output_nV_sqrtHz=float(y*1e9),input_nV_sqrtHz=float(z*1e9)) for x,y,z in zip(f,out,inp)])
    table('noise_summary.csv',noise)
    high=points[-1];rr=execute('validation_thd_halfstep',final(stage,'tran',vc=high['vc'],amp=TARGET/16,stop=40,dt=1),dict(stage=stage,gain=16,dt_ns=1))[0]
    hh=harmonics(rr);baseline=chosen['rows'][-1]
    checks=[dict(check='high_gain_half_max_timestep_2ns_to_1ns',fundamental_change_pct=100*(hh['fundamental_pp_V']/baseline['fundamental_Vpp']-1),THD_difference_percentage_points=hh['THD_pct']-baseline['THD_pct'])]
    if control:
        ki=control['ki_per_s'];tr=(.259,.036,200);rr=execute('validation_agc_halfstep',agc(stage,points,amp=tr[0],ki=ki,dt=2.5,stop=500,transition=tr),dict(stage=stage,ki=ki,transition=tr,dt_ns=2.5))[0]
        m=cyc_metrics(rr,'validation_agc_halfstep',tr[0],ki,tr);base=[r for r in json.loads((OUT/'controller_selection.json').read_text())['dynamic'] if r['ki_per_s']==ki and r['after_Vpp']==.036][0]
        checks.append(dict(check='AGC_half_max_timestep_5ns_to_2.5ns',baseline_recovery_us=base['settling_us'],refined_recovery_us=m['settling_us'],amplitude_change_pct=100*(m['output_Vpp']/base['output_Vpp']-1),control_ripple_change_mV=m['control_ripple_mV']-base['control_ripple_mV']))
    dump('validation.json',checks)
    dump('selected_core_summary.json',dict(stage=stage,control=control,operating_points=rows,noise=noise,validation=checks))

def cascade_study(chosen,control):
    if not control:return
    tia=json.loads((ROOT.parent/'tia'/'selection.json').read_text());stage=chosen['stage'];tag=chosen['tag']
    points=json.loads((OUT/(tag+'_points.json')).read_text());ki=control['ki_per_s']
    assert hashlib.sha256((ROOT/'models'/'original_tia.lib').read_bytes()).hexdigest()==tia['original_model_sha256']
    tia_block=f'''
.include ../../models/original_tia.lib
VDDTIA VDDT 0 1.8
VREFTIA REFT 0 .9
IDARK DET 0 20n
IBACK DET 0 1.98u
ISIGNAL DET 0 SINE(0 {{ipp/2}} 1Meg) AC 1
CD DET 0 {tia['detector_capacitance_f']}
RFTIA TI_OUT DET {tia['feedback_resistance_ohm']}
CFTIA TI_OUT DET {tia['feedback_capacitance_f']}
XTIA REFT DET TI_OUT VDDT 0 CMOS_OPAMP CCOMP=1p BIAS_SCALE=1
CLTIA TI_OUT 0 1p
'''
    def linked(s,ipp):
        return s.replace('VIN VIN 0 SINE({vcm} {amp/2} {freq}) AC 1','CCOUP TI_OUT VIN 10n\nRBIAS VIN REF 1Meg').replace(' I(VIN)','').replace('.save ','.save V(TI_OUT) V(DET) I(VDDTIA) I(ISIGNAL) ').replace('.end',f'.param ipp={ipp}\n'+tia_block+'.end')
    records=execute('cascade_ac',linked(cases(stage,'ac',[dict(vc=points[j]['vc']) for j in [0,2,4]],ppd=160),1e-6),dict(stage=stage,TIA=tia,gains=[1,4,16],coupling_F=1e-8,bias_resistance_ohm=1e6))
    acrows=[]
    for p,r in zip([points[j] for j in [0,2,4]],records):
        f=r['frequency'].real
        aa=ac(r)
        acrows.append(dict(gain_setting=p['target_gain'],gain_TIA_to_input_1MHz_ohm=float(interp(f,abs(r['v(vin)']),1e6)),total_transimpedance_1MHz_ohm=aa['gain_1M'],bandwidth_MHz=aa['bandwidth_MHz'],peaking_dB=aa['peaking_dB']))
    table('cascade_ac.csv',acrows)
    # AC probe at middle gain provides an initial current selection; actual loaded
    # VGA input waveform is measured in each AGC test and not asserted equal.
    z=acrows[1]['gain_TIA_to_input_1MHz_ohm'];rows=[]
    for a in [.036,.104,.259]:
        ipp=a/z;name=f'cascade_agc_{round(a*1000)}mV'
        r=execute(name,linked(agc(stage,points,ki=ki),ipp),dict(stage=stage,ki=ki,target_Vpp=TARGET,nominal_input_Vpp=a,current_source_pp_A=ipp,TIA=tia))[0]
        m=cyc_metrics(r,name,a,ki);hi=harmonics(r,node='v(vin)');ht=harmonics(r,node='v(ti_out)')
        m.update(current_source_pp_A=ipp,nominal_input_Vpp=a,actual_VGA_input_Vpp=hi['vpp_V'],actual_TIA_output_Vpp=ht['vpp_V'],TIA_THD_pct=ht['THD_pct'])
        rows.append(m)
    table('cascade_agc.csv',rows);dump('cascade_summary.json',dict(ac=acrows,agc=rows,coupling_F=1e-8,bias_resistance_ohm=1e6,scope='actual transistor-level TIA-VGA coupling with behavioural AGC, not ideal voltage substitution'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['architecture','controller','validation','cascade','all'],default='all');args=parser.parse_args()
    if args.stage in ['architecture','all']:chosen=stage_study()
    else:
        s=json.loads((OUT/'stage_selection.json').read_text());chosen=next((c for c in s['candidates'] if c['stage']==s['selected_stage']),None)
    if not chosen:print('Neither architecture passed the fixed criteria.',flush=True);return
    if args.stage in ['controller','all']:control=controller_study(chosen)
    else:control=json.loads((OUT/'controller_selection.json').read_text())['selected'] if (OUT/'controller_selection.json').exists() else None
    if args.stage in ['validation','all']:validation(chosen,control)
    if args.stage in ['cascade','all']:cascade_study(chosen,control)
    dump('conditions_last_invocation.json',CONDS)

if __name__=='__main__':main()
