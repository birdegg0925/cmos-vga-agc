"""Run one archived AC deck in a detached scratch tree; never alter reference data."""
from pathlib import Path
import argparse, os, tempfile, shutil, subprocess, fcntl, json, math, cmath
ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--runner',default=os.environ.get('LTSPICE_RUNNER','/Applications/LTspice.app/Contents/SharedSupport/ltspice/LTspice/run_ltspice'));args=parser.parse_args()
scratch=Path(tempfile.mkdtemp(prefix='vga-smoke-'))
shutil.copytree(ROOT/'vga/models',scratch/'models')
run=scratch/'runs/stage8x8_ac';run.mkdir(parents=True)
shutil.copyfile(ROOT/'vga/runs/stage8x8_ac/test.cir',run/'test.cir')
lock=Path(os.environ.get('LTSPICE_LOCK',str(ROOT/'.ltspice_serial.lock')))
with lock.open('a') as f:
    fcntl.flock(f,fcntl.LOCK_EX)
    p=subprocess.run([args.runner,'-b','-ascii','test.cir'],cwd=run,env={**os.environ,'WINEDEBUG':'-all','MVK_CONFIG_LOG_LEVEL':'0'},capture_output=True,timeout=180)
(run/'runner.log').write_bytes(p.stdout+p.stderr)
log=(run/'test.log').read_text(errors='replace') if (run/'test.log').exists() else ''
success=p.returncode==0 and (run/'test.raw').is_file() and 'Total elapsed time' in log
report={'success':success,'analysis':'fixed-gain AC sweep at five calibrated controls','scratch':str(scratch),'returncode':p.returncode,'reference_results_changed':False}
if success:
    lines=(run/'test.raw').read_text().splitlines(); start=lines.index('Values:')+1
    nvar=int(next(s.split(':',1)[1] for s in lines if s.startswith('No. Variables:')))
    data=[]
    for k in range(start,len(lines),nvar):
        block=lines[k:k+nvar]
        if len(block)<nvar:continue
        values=[]
        for j,line in enumerate(block):
            value=line.split()[-1];parts=value.split(',');values.append(complex(float(parts[0]),float(parts[1])) if len(parts)>1 else complex(float(value),0))
        data.append(values)
    groups=[]
    for row in data:
        if not groups or row[0].real<groups[-1][-1][0].real:groups.append([])
        groups[-1].append(row)
    results=[]
    for group in groups:
        near=min(group,key=lambda row:abs(math.log(row[0].real/1e6)))
        results.append(abs(near[1]))
    assert len(results)==5 and all(abs(g/t-1)<.03 for g,t in zip(results,[1,2,4,8,16])),results
    report['nearest_1MHz_gain_magnitudes']=results;report['five_gain_sanity_pass']=True
print(json.dumps(report,indent=2))
if not success:raise SystemExit('LTspice failed; inspect scratch runner.log and test.log.')
