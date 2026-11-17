"""Only aggregate results reach stdout; source-level traces stay private."""
import argparse
import json
import sys
from .config import PipelineError
from .pipeline import run_pipeline, validate_pipeline_output


def main(argv=None):
    parser = argparse.ArgumentParser(description='Configurable local spend pipeline')
    commands = parser.add_subparsers(dest='command',required=True)
    for cmd in ('run','validate'):
        sub = commands.add_parser(cmd)
        sub.add_argument('--config',required=True)
        sub.add_argument('--input-root',required=True)
        sub.add_argument('--output',required=True)
        if cmd == 'run':
            sub.add_argument('--diagnostics')
            sub.add_argument('--artifact',help='Trusted locally trained private model; omitted for zero-label mode')
    train = commands.add_parser('train',help='Fit an optional private text model from explicit labels')
    train.add_argument('--config',required=True)
    train.add_argument('--input-root',required=True)
    train.add_argument('--labels',required=True)
    train.add_argument('--artifact',required=True)
    train.add_argument('--label-id-column',default='record_id')
    train.add_argument('--label-columns',nargs='+',default=['category_l1','category_l2','category_l3'])
    train.add_argument('--partitions')
    train.add_argument('--partition-id-prefix',default='')
    train.add_argument('--all-labels',action='store_true',help='Explicit full-data final fit; no heldout accuracy claim')
    evaluate = commands.add_parser('evaluate',help='Score saved predictions separately from inference')
    evaluate.add_argument('--prediction',required=True)
    evaluate.add_argument('--labels',required=True)
    evaluate.add_argument('--raw')
    evaluate.add_argument('--output',required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            result = run_pipeline(args.config,args.input_root,args.output,args.diagnostics,args.artifact)
        elif args.command == 'train':
            from .config import load_config,input_path
            from .ingest import ingest
            from .classify import load_taxonomy
            from .supervised import train_model
            if args.all_labels and args.partitions:
                raise PipelineError('Choose --partitions or --all-labels, not both')
            config = load_config(args.config)
            records,_ = ingest(config,args.input_root)
            paths = load_taxonomy(input_path(args.input_root,config['taxonomy']['file']),config['taxonomy']['columns'])
            result = train_model(records,args.labels,args.artifact,label_id_column=args.label_id_column,label_columns=args.label_columns,
                                 partitions_path=args.partitions,train_splits=('all',) if args.all_labels else ('development',),
                                 partition_id_prefix=args.partition_id_prefix,valid_paths=paths)
        elif args.command == 'evaluate':
            from .diagnostics import check_private_path
            from evaluation.real import evaluate_saved
            target = check_private_path(args.output)
            result = evaluate_saved(args.prediction,args.labels,args.raw)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(result,indent=2)+'\n')
        else:
            result = validate_pipeline_output(args.config,args.input_root,args.output)
    except (PipelineError,ValueError,OSError,RuntimeError,ImportError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 2
    # No row-level values or identifiers in CLI output.
    print(json.dumps(result,default=str,sort_keys=True))
    return 0
