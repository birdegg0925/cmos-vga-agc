#!/usr/bin/env python3
"""Calculate circuit metrics from LTspice ASCII raw output."""
from pathlib import Path
import numpy as np
from scipy.signal import find_peaks
ROOT=Path(__file__).resolve().parents[1]

def raw(path):
    data=Path(path).read_bytes();txt=data.decode('utf-16') if data[:2] in [b'\xff\xfe',b'\xfe\xff'] else data.decode('latin1');lines=txt.splitlines()
    a=lines.index('Variables:');b=lines.index('Values:');names=[x.split()[1].lower() for x in lines[a+1:b] if x.strip()]
    def num(x):
        v=x.split(',');return complex(float(v[0]),float(v[1])) if len(v)==2 else float(x)
    vals=[]
    for i in range(b+1,len(lines),len(names)):
        block=lines[i:i+len(names)]
        if len(block)==len(names):vals.append([num(block[0].split()[-1])]+[num(x.strip()) for x in block[1:]])
    ar=np.asarray(vals);axis=ar[:,0].real;breaks=np.r_[0,np.flatnonzero(np.diff(axis)<0)+1,len(ar)]
    return [{n:ar[l:r,j] for j,n in enumerate(names)} for l,r in zip(breaks[:-1],breaks[1:])]

def load(name):return raw(ROOT/'runs'/name/'test.raw')
def interp(f,y,x):return np.interp(np.log10(x),np.log10(f),y)
def ac(r):
    f=r['frequency'].real;v=r['v(out)'];g=abs(v);ref=interp(f,g,1e5);peak=g.max();target=ref/np.sqrt(2)
    inds=np.where((f>1e5)&(g<=target))[0];bw=np.nan
    if len(inds):
        i=inds[0];bw=10**np.interp(target,[g[i],g[i-1]],[np.log10(f[i]),np.log10(f[i-1])])
    return dict(gain_100k=ref,gain_1M=interp(f,g,1e6),bandwidth_MHz=bw/1e6,peaking_dB=20*np.log10(peak/ref))

def harmonics(r,freq=1e6,cycles=20,spp=1000,node='v(out)',end=None):
    t=r['time'].real;y=r[node].real;end=(np.floor(t[-1]*freq+1e-6)/freq if end is None else end);start=end-cycles/freq
    tu=start+np.arange(cycles*spp)/(freq*spp);yu=np.interp(tu,t,y);z=np.fft.rfft(yu-yu.mean())*2/len(yu)
    amps=np.array([abs(z[k*cycles]) for k in range(1,11)])
    return dict(fundamental_pp_V=2*amps[0],vpp_V=float(yu.max()-yu.min()),THD_pct=100*np.linalg.norm(amps[1:])/amps[0],mean_V=yu.mean(),peak_min_V=yu.min(),peak_max_V=yu.max(),window_start_us=start*1e6,window_end_us=end*1e6,harmonic_peak_V=amps.tolist())

if __name__=='__main__':
    import sys
    for name in sys.argv[1:]:
        for r in load(name):print(name,ac(r) if 'frequency' in r and 'v(out)' in r else harmonics(r) if 'time' in r else {k:v[0] for k,v in r.items() if k in ['v(out)','i(vdd)']})
