"""Check local model resolution, archived summaries and generated cascade deck."""
from pathlib import Path
import sys, json, hashlib, csv
ROOT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
tia=json.loads((ROOT/'tia/selection.json').read_text())
assert hashlib.sha256((ROOT/'vga/models/original_tia.lib').read_bytes()).hexdigest()==tia['original_model_sha256']
st=json.loads((ROOT/'vga/results/stage_selection.json').read_text());c=next(r for r in st['candidates'] if r['stage']==st['selected_stage'])
control=json.loads((ROOT/'vga/results/controller_selection.json').read_text())['selected']
decks=list((ROOT/'vga/runs').glob('*/test.cir'))
assert len(decks)>20
for deck in decks:
    content=deck.read_text()
    assert '/Users/' not in content
    for item in [line.split(None,1)[1] for line in content.splitlines() if line.startswith('.include ')]:
        p=(deck.parent/item).resolve()
        assert p.is_relative_to(ROOT) and p.is_file()
cs=json.loads((ROOT/'vga/results/cascade_summary.json').read_text())
assert len(cs['agc'])==3 and all(abs(r['output_Vpp']-.35)<.001 for r in cs['agc'])
assert control['ki_per_s']==87000
assert c['all_pass'] and all(r['passes'] for r in c['rows'])
selection=json.loads((ROOT/'vga/results/controller_selection.json').read_text())
passing=[r for r in selection['candidates'] if r['passes']]
assert min(passing,key=lambda r:r['worst_recovery_us'])['ki_per_s']==control['ki_per_s']
assert all(7 < r['bandwidth_MHz'] < 7.3 for r in cs['ac'])
report={'status':'PASS','local_dependencies_only':True,'netlists_checked':len(decks),'original_TIA_model_hash':'PASS','recorded_architecture_and_controller_selection':'PASS','cascade_sanity':'PASS','fresh_SPICE_simulation':False}
if '--generated-deck' in sys.argv:
    sys.path.insert(0,str(ROOT/'vga'));import study
    assert Path(study.oldrun.__file__).resolve().is_relative_to(ROOT)
    captured={}
    class PreparedOnly(Exception):pass
    def capture(name,deck,condition=None):captured.update(name=name,deck=deck);raise PreparedOnly()
    study.execute=capture
    try:study.cascade_study(c,control)
    except PreparedOnly:pass
    packaged=(ROOT/'vga/runs/cascade_ac/test.cir').read_text()
    assert captured['deck']==packaged
    report['generated_cascade_deck_matches_packaged']=True
print(json.dumps(report,indent=2))
