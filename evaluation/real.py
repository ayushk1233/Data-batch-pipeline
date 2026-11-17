"""Offline saved-output evaluator; labels are never passed to the pipeline."""
import argparse
import csv
from collections import defaultdict, Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from evaluation.metrics import classification_metrics, grouping_metrics, reliability_bins


def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as h:
        return list(csv.DictReader(h))


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluate_saved(prediction, labels, raw=None, split_manifests=None):
    # Prediction loaded and hashed before any reference labels are opened.
    prediction_hash=_hash(prediction)
    output={r['record_id']:r for r in rows(prediction)}
    gold=rows(labels)
    raw_rows=rows(raw) if raw else []
    raw_map={('ERP:' if 'value_zar' in r else '')+r['line_id']:r for r in raw_rows}
    pairs=[];missing=[];supplier=[];item=[];pairs_by_id={}
    included_support=0;inclusion_confusion=Counter();confidence=[];matched_labels=0
    for g in gold:
        rid=g.get('record_id',g.get('line_id',''))
        p=output.get(rid)
        if not p:continue
        matched_labels+=1
        if g.get('include','').strip() in ('0','1'):
            reference='INCLUDED' if g['include'].strip()=='1' else g.get('exclusion_reason','').strip()
            predicted='INCLUDED' if p['include']=='1' else p['exclusion_reason']
            inclusion_confusion[reference,predicted]+=1
        gp=tuple(g.get(f'category_l{i}','') for i in range(1,5))
        if not any(gp):continue
        pp=tuple(p.get(f'l{i}','') for i in range(1,5))
        raw_record=raw_map.get(rid,{})
        # Reference spend is independently taken from ERP's supplied net amount.
        amount=raw_record.get('value_zar','0')
        try: weight=abs(Decimal(amount.replace(',','')))
        except Exception:weight=Decimal(0)
        confidence.append((float(p['confidence']),float(gp==pp)))
        pair=(gp,pp,weight);pairs.append(pair);pairs_by_id[rid]=pair
        if not (raw_record.get('material_short_text','').strip() or raw_record.get('service_short_text','').strip() or raw_record.get('line_description','').strip()):missing.append(pair)
        included_support+=p['include']=='1'
        supplier.append((g.get('supplier_key',''),p['supplier_key']))
        item.append((g.get('item_key',''),p['item_key']))
    grouped={}
    for manifest_path in split_manifests or []:
        assignments=json.loads(Path(manifest_path).read_text())['assignments']
        slices=defaultdict(list)
        for rid,pair in pairs_by_id.items():
            membership=assignments.get(rid.removeprefix('ERP:'),{})
            if membership:slices[membership['split']].append(pair)
        grouped[Path(manifest_path).stem]={split:classification_metrics(values) for split,values in slices.items()}
    inclusion={}
    for label in sorted({g for g,p in inclusion_confusion}|{p for g,p in inclusion_confusion}):
        tp=inclusion_confusion[label,label]
        support=sum(n for (g,p),n in inclusion_confusion.items() if g==label)
        predicted=sum(n for (g,p),n in inclusion_confusion.items() if p==label)
        inclusion[label]={'support':support,'predicted':predicted,
                          'precision':tp/predicted if predicted else None,
                          'recall':tp/support if support else None,
                          'f1':2*tp/(support+predicted) if support+predicted else None}
    supplied_inclusion={'support':sum(inclusion_confusion.values()),'by_reason':inclusion,
                        'macro_f1':sum(v['f1'] for v in inclusion.values())/len(inclusion) if inclusion else None,
                        'confusion':{f'{g} -> {p}':n for (g,p),n in sorted(inclusion_confusion.items())},
                        'scope':'comparison with supplied seed labels, which are incomplete and noisy; not independently verified exclusion truth'}
    return {'supplied_inclusion_labels':supplied_inclusion,
            'confidence':{'support':len(confidence),'calibration':'uncalibrated ranking score',
                          'brier':sum((c-y)**2 for c,y in confidence)/len(confidence) if confidence else None,
                          'reliability_bins':reliability_bins(confidence)},
            'matched_label_rows':matched_labels,'unmatched_label_rows':len(gold)-matched_labels,
            'grouped_reservations':grouped,'prediction_sha256':prediction_hash,'label_rows':len(gold),
            'matched_labelled_paths':len(pairs),'predicted_included_labelled_paths':included_support,
            'classification':classification_metrics(pairs),'missing_description':classification_metrics(missing),
            'supplier_grouping':grouping_metrics(supplier),'item_grouping':grouping_metrics(item),
            'scope':'saved predictions scored after output; producer training provenance is not verified by this scorer. Report labels-hidden only with supporting producer evidence. Supplied labels are incomplete/noisy; A has no include/duplicate truth',
            'spend_weighting':'A absolute net ERP amount where raw supplied; B weighted metrics are null because local currencies cannot be mixed and independent USD reference amounts are unavailable'}


def reserve_splits(raw_path, output_path, group_fields):
    """Stable grouped split assignment before fitting; no labels needed."""
    source=rows(raw_path)
    parents=list(range(len(source)))
    def find(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    seen={}
    for i,row in enumerate(source):
        for field in group_fields:
            value=' '.join(row.get(field,'').casefold().split())
            if not value:continue
            token=(field,value)
            if token in seen:
                left,right=find(i),find(seen[token])
                parents[max(left,right)]=min(left,right)
            else:seen[token]=i
    members=defaultdict(list)
    for i,row in enumerate(source):members[find(i)].append(row['line_id'])
    group_hashes={key:hashlib.sha256('\x1f'.join(sorted(ids)).encode()).hexdigest() for key,ids in members.items()}
    groups={}
    for i,row in enumerate(source):
        group_hash=group_hashes[find(i)]
        bucket=int(group_hash[:8],16)%10
        split='development' if bucket<6 else 'calibration' if bucket<8 else 'test'
        groups[row['line_id']]={'group_hash':group_hash,'split':split}
    artifact={'raw_sha256':_hash(raw_path),'group_fields':group_fields,'assignments':groups,
              'warning':'Use separate item/supplier/temporal/source holdouts; this is a grouped reservation, not an evaluated model score.'}
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    Path(output_path).write_text(json.dumps(artifact,indent=2))
    return artifact


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prediction',required=True);p.add_argument('--labels',required=True)
    p.add_argument('--raw');p.add_argument('--output',required=True)
    p.add_argument('--split-manifest',action='append',default=[])
    a=p.parse_args(argv)
    result=evaluate_saved(a.prediction,a.labels,a.raw,a.split_manifest)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
