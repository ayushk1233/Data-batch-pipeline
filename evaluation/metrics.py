"""Independent, dependency-free evaluation of saved predictions and event truth."""
from collections import Counter, defaultdict
from decimal import Decimal
import math

COLUMNS = ['record_id','include','exclusion_reason','supplier_key','item_key','spend','l1','l2','l3','l4','confidence']


def _ratio(a, b):
    return a / b if b else None


def _f1(precision, recall):
    if precision is None or recall is None:
        return None
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def classification_metrics(pairs):
    """pairs contain (truth_path, predicted_path, absolute_reference_weight)."""
    pairs = list(pairs)
    n = len(pairs)
    support = Counter(tuple(g) for g, _, _ in pairs)
    predicted = Counter(tuple(p) for _, p, _ in pairs)
    correct = Counter(tuple(g) for g, p, _ in pairs if tuple(g) == tuple(p))
    labels = set(support) | set(predicted)
    f1s = []
    for label in labels:
        f1s.append(2 * correct[label] / (support[label] + predicted[label]))
    weight = sum((Decimal(str(w)) for _, _, w in pairs), Decimal(0))
    exact = sum(tuple(g) == tuple(p) for g, p, _ in pairs)
    levels = {}
    for depth in range(1, 5):
        scored = [(g, p, Decimal(str(w))) for g, p, w in pairs if len(g) >= depth and g[depth-1]]
        denom = sum((w for _, _, w in scored), Decimal(0))
        levels[f'l{depth}'] = {
            'support': len(scored),
            'accuracy': _ratio(sum(tuple(g[:depth]) == tuple(p[:depth]) for g, p, _ in scored), len(scored)),
            'spend_weighted_accuracy': float(sum((w for g,p,w in scored if tuple(g[:depth]) == tuple(p[:depth])), Decimal(0)) / denom) if denom else None,
        }
    return {'support': n, 'exact_path_accuracy': _ratio(exact,n),
            'macro_f1': sum(f1s)/len(f1s) if f1s else None,
            'spend_weighted_exact_accuracy': float(sum((Decimal(str(w)) for g,p,w in pairs if tuple(g)==tuple(p)), Decimal(0))/weight) if weight else None,
            'levels': levels}


def grouping_metrics(pairs):
    """Contingency-table pairwise and B-cubed scores; key spellings never compared."""
    pairs = [(str(g), str(p)) for g,p in pairs if g]
    gold = Counter(g for g,_ in pairs)
    pred = Counter(p for _,p in pairs)
    joint = Counter(pairs)
    choose = lambda n: n*(n-1)//2
    tp = sum(choose(v) for v in joint.values())
    gp = sum(choose(v) for v in gold.values())
    pp = sum(choose(v) for v in pred.values())
    n=len(pairs)
    precision=_ratio(tp,pp)
    recall=_ratio(tp,gp)
    return {'support':n,'true_pairs':gp,'predicted_pairs':pp,'correct_pairs':tp,
            'pairwise_precision':precision,'pairwise_recall':recall,'pairwise_f1':_f1(precision,recall),
            'bcubed_precision':sum(v*v/pred[p] for (g,p),v in joint.items())/n if n else None,
            'bcubed_recall':sum(v*v/gold[g] for (g,p),v in joint.items())/n if n else None}


def reliability_bins(confidence):
    buckets=defaultdict(list)
    for c,y in confidence:
        buckets[min(9,int(c*10))].append((c,y))
    bins=[]
    for i in range(10):
        members=buckets[i]
        bins.append({'lower':i/10,'upper':(i+1)/10,'support':len(members),
                     'mean_confidence':sum(c for c,y in members)/len(members) if members else None,
                     'exact_accuracy':sum(y for c,y in members)/len(members) if members else None})
    return bins


def score_predictions(truth, predictions, paths):
    """Truth comes from event ledger, never production normalisation or exclusions."""
    truth={r['record_id']:r for r in truth}
    counts=Counter(r['record_id'] for r in predictions)
    pred={r['record_id']:r for r in predictions}
    allowed=set(tuple(p) for p in paths)
    contract_errors=[]
    if set(truth)!=set(pred) or any(n!=1 for n in counts.values()):
        contract_errors.append('record_id_multiset')
    shared=set(truth)&set(pred)
    financial=[]
    classes=[]
    confusion=Counter()
    confidence=[]
    valid_paths=0
    for rid in sorted(shared):
        g,p=truth[rid],pred[rid]
        inc=str(p.get('include'))=='1'
        gp=tuple(g['path'])
        pp=tuple(p.get(f'l{i}','') for i in range(1,5))
        reason=p.get('exclusion_reason','')
        try:
            value=Decimal(str(p['spend']))
            cf=float(p['confidence'])
            if not value.is_finite() or not math.isfinite(cf) or not 0<=cf<=1:
                raise ValueError('nonfinite value')
        except (ValueError, ArithmeticError, KeyError):
            contract_errors.append('invalid_number'); continue
        if inc:
            if reason or pp not in allowed:
                contract_errors.append('included_reason_or_taxonomy')
            else:
                valid_paths+=1
        elif reason not in {'CANCELLED','NOT_APPROVED','NON_PROCUREMENT','DUPLICATE'} or any(pp) or value!=0:
            contract_errors.append('excluded_contract')
        financial.append((Decimal(g['spend']),value))
        gc='INCLUDED' if g['include'] else g['reason']
        pc='INCLUDED' if inc else reason
        confusion[(gc,pc)]+=1
        if g['include']:
            classes.append((gp,pp,abs(Decimal(g['spend']))))
            confidence.append((cf,float(gp==pp)))
    reason_scores={}
    for label in sorted({g for g,p in confusion}|{p for g,p in confusion}):
        tp=confusion[label,label]
        support=sum(v for (g,p),v in confusion.items() if g==label)
        predicted=sum(v for (g,p),v in confusion.items() if p==label)
        pr=_ratio(tp,predicted); re=_ratio(tp,support)
        reason_scores[label]={'support':support,'predicted':predicted,'precision':pr,'recall':re,'f1':_f1(pr,re)}
    f1s=[v['f1'] if v['f1'] is not None else 0 for v in reason_scores.values()]
    errors=[abs(p-g) for g,p in financial]
    gtotal=sum((g for g,p in financial),Decimal(0))
    ptotal=sum((p for g,p in financial),Decimal(0))
    false_removed=[rid for rid in shared if truth[rid]['include'] and str(pred[rid]['include'])!='1']
    dup_tp=sum(1 for rid in shared if truth[rid]['reason']=='DUPLICATE' and pred[rid]['exclusion_reason']=='DUPLICATE')
    dup_gold=sum(g['reason']=='DUPLICATE' for g in truth.values())
    dup_pred=sum(p['exclusion_reason']=='DUPLICATE' for p in predictions)
    informative=[(tuple(truth[rid]['path']), tuple(pred[rid].get(f'l{i}','') for i in range(1,5)), abs(Decimal(truth[rid]['spend']))) for rid in shared if truth[rid]['include'] and truth[rid].get('informative',True)]
    return {'rows':len(predictions),'expected_rows':len(truth),'contract_errors':dict(Counter(contract_errors)),
            'included_valid_paths':valid_paths,'financial':{
                'reference_total':str(gtotal),'predicted_total':str(ptotal),'signed_error':str(ptotal-gtotal),
                'absolute_line_error_sum':str(sum(errors,Decimal(0))),
                'max_line_error':str(max(errors,default=Decimal(0))),
                'lines_within_one_cent':sum(e<=Decimal('.01') for e in errors),'support':len(errors)},
            'inclusion':{'macro_f1':sum(f1s)/len(f1s) if f1s else None,'by_reason':reason_scores,
                         'confusion':{f'{g} -> {p}':v for (g,p),v in sorted(confusion.items())},
                         'legitimate_rows_removed':len(false_removed),
                         'legitimate_spend_removed':str(sum((Decimal(truth[r]['spend']) for r in false_removed),Decimal(0)))},
            'duplicates':{'support':dup_gold,'predicted':dup_pred,'precision':_ratio(dup_tp,dup_pred),'recall':_ratio(dup_tp,dup_gold)},
            'classification':classification_metrics(classes),'informative_classification':classification_metrics(informative),
            'supplier_grouping':grouping_metrics((truth[r].get('supplier',''),pred[r]['supplier_key']) for r in shared),
            'item_grouping':grouping_metrics((truth[r].get('item',''),pred[r]['item_key']) for r in shared),
            'confidence':{'reliability_bins':reliability_bins(confidence),'scope':'uncalibrated exact-path confidence on reference-included records',
                          'brier':sum((c-y)**2 for c,y in confidence)/len(confidence) if confidence else None}}
