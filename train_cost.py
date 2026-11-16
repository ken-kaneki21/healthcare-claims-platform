"""Train a forward-looking cost baseline and ridge model on the generated database."""
import argparse
import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np


def cohort(db, index, *, include_target=True):
    return np.array(db.execute("""
        WITH cutoffs AS (
            SELECT starts cutoff,date(starts,'+3 months') target_end
            FROM month WHERE id=:index
        ), history AS (
            SELECT c.client_id,c.member_id,
                   SUM(CASE WHEN c.month_id>=:index-3 THEN p.delta_cents ELSE 0 END) recent,
                   SUM(p.delta_cents) six_month_cost,count(DISTINCT c.id) claims
            FROM claim c JOIN payment_event p ON p.claim_id=c.id CROSS JOIN cutoffs
            WHERE c.month_id BETWEEN :index-6 AND :index-1 AND p.received_date<cutoff
            GROUP BY c.client_id,c.member_id
        ), target AS (
            SELECT c.client_id,c.member_id,SUM(p.delta_cents) cost
            FROM claim c JOIN payment_event p ON p.claim_id=c.id CROSS JOIN cutoffs
            WHERE :include_target AND c.month_id BETWEEN :index AND :index+2
              AND p.received_date<date(target_end,'+90 days')
            GROUP BY c.client_id,c.member_id
        )
        SELECT m.client_id,m.id,m.age_band,m.cohort='high_needs',
               COALESCE(h.recent,0)/100.0,COALESCE(h.six_month_cost,0)/100.0,
               COALESCE(h.claims,0),COALESCE(t.cost,0)/100.0
        FROM member m
        JOIN member_month e ON e.client_id=m.client_id AND e.member_id=m.id AND e.month_id=:index-1
        LEFT JOIN history h ON h.client_id=m.client_id AND h.member_id=m.id
        LEFT JOIN target t ON t.client_id=m.client_id AND t.member_id=m.id
        ORDER BY m.client_id,m.id
    """, {"index": index, "include_target": include_target}).fetchall(), dtype=np.float64).reshape(-1, 8)


def predict_values(rows, model):
    normalized = (rows[:, 2:-1] - model["mean"]) / model["scale"]
    return np.maximum(0, model["intercept"] + normalized @ model["coefficients"])


def train(database, output):
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro",uri=True)) as db:
        training = np.concatenate([cohort(db, index) for index in (7,10,13)])
        held_out = cohort(db, 21)
    training = training[(training[:,0]==1)&(training[:,1]%5!=0)]
    features = training[:,2:-1]
    mean = features.mean(axis=0)
    scale = features.std(axis=0)
    scale[scale==0] = 1
    x = (features-mean)/scale
    y = training[:,-1]
    intercept = float(y.mean())
    coefficients = np.linalg.solve(x.T @ x + 100*np.eye(x.shape[1]),x.T @ (y-intercept))
    evaluation = []
    for name, mask in (
        ("later_period_unseen_members", (held_out[:,0]==1)&(held_out[:,1]%5==0)),
        ("later_period_unseen_client", held_out[:,0]==2),
    ):
        rows = held_out[mask]
        model = np.maximum(0,intercept+((rows[:,2:-1]-mean)/scale) @ coefficients)
        baseline = rows[:,4]
        truth = rows[:,-1]
        evaluation.append({"split":name,"rows":len(rows),
                           "baseline_mae_usd":float(np.abs(baseline-truth).mean()),
                           "ridge_mae_usd":float(np.abs(model-truth).mean())})
    report = {
        "model_version":"ridge-1","target":"paid cost in the following three months, USD",
        "features":["age_band","high_needs","paid_3_months_usd","paid_6_months_usd","claim_count_6_months"],
        "training_periods":[7,10,13],"evaluation_period":21,"training_rows":len(training),
        "mean":mean.tolist(),"scale":scale.tolist(),"intercept":intercept,
        "coefficients":coefficients.tolist(),"evaluation":evaluation,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    return report


def predict(database, model_path, index, output):
    model = json.loads(model_path.read_text(encoding="utf-8"))
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro",uri=True)) as db:
        rows = cohort(db, index, include_target=False)
    values = predict_values(rows, model)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("w",encoding="utf-8",newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("client_id","member_id","period","model_version","predicted_cost_usd"))
        writer.writerows((int(row[0]),int(row[1]),index,model["model_version"],round(cost,2))
                         for row,cost in zip(rows,values))
    return {"predictions":len(rows),"period":index,"model_version":model["model_version"]}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--model",type=Path)
    parser.add_argument("--period",type=int,choices=range(7,25),metavar="7..24")
    args=parser.parse_args()
    if (args.period is None)!=(args.model is None):
        parser.error("prediction requires both --model and --period")
    result = train(args.database,args.out) if args.model is None else predict(
        args.database,args.model,args.period,args.out)
    print(json.dumps(result,indent=2))
