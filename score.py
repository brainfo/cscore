import pandas as pd
import os
import numpy as np
import multiprocessing
import sklearn
from itertools import repeat
import pkg_resources
import argparse

parser = argparse.ArgumentParser()

parser.add_argument('-i','--input_folder', action='store', dest='input_folder', help='the path contains the comparison stats files')
parser.add_argument('-a','--comp1_file', action='store', dest='comp1_file', help='first comparison file')
parser.add_argument('-b','--comp2_file', action='store', dest='comp2_file', help='second comparison file')
parser.add_argument('-o','--output_file', action='store', dest='output_file', help='output file, each row assigned with a c-score, a p-value, and a sense field. If the mode is gene, then also with a pc filed indicating whether a gene (row) is protein-coding.')
parser.add_argument("-m", "--mode", choices=['gene','pathway'], dest='mode', default ='gene')
parser.add_argument("-e", "--effect", dest ="effect", default="avg_log2FC")
parser.add_argument("-n", "--gname", dest ="gname", default="Unnamed: 0")
parser.add_argument("-f", "--fdr", dest ="fdr", default="p_val_adj")
parser.add_argument('-g','--gtf', action='store', dest='gtf_file', help='gene annotation gtf for protein-coding annotation')

paras = parser.parse_args()

comp1_file = os.path.join(paras.input_folder, paras.comp1_file)
comp2_file = os.path.join(paras.input_folder, paras.comp2_file)
output_file = paras.output_file
mode = paras.mode
gtf_file = paras.gtf_file
effect = paras.effect
gname = paras.gname
fdr = paras.fdr
# make a summary list of coding genes
# in the hope of increasing the significance of the pathways
def gene_info(x):
    # Extract gene names, gene_type, gene_status and level
    g_name = list(filter(lambda x: 'gene_name' in x,  x.split(";")))[
        0].split(" ")[2].strip('\"')
    g_type = list(filter(lambda x: 'gene_type' in x,  x.split(";")))[
        0].split(" ")[2]
    return (g_name, g_type)

if gtf_file:
    gencode = pd.read_table(gtf_file, comment="#",
                        sep="\t", names=['seqname', 'source', 'feature', 'start', 'end', 'score', 'strand', 'frame', 'attribute'])

    gencode_genes = gencode[(gencode.feature == "transcript")][[
    'seqname', 'start', 'end', 'attribute']].copy().reset_index().drop('index', axis=1)
    gencode_genes["gene_name"], gencode_genes["gene_type"] = zip(
    *gencode_genes.attribute.apply(lambda x: gene_info(x)))
    pc_genes = gencode_genes.query(
    "gene_type=='\"protein_coding\"'")
    pc_gene_set = set(pc_genes.gene_name)

def weight(fdr):
    return np.where(fdr < 0.05, 1, np.log10(fdr)/np.log10(0.05))
def ratio(fc_comp1, fc_comp2):
    df = pd.DataFrame({'fc_comp1': fc_comp1, 'fc_comp2': fc_comp2})
    return np.where(fc_comp1*fc_comp2 > 0, np.maximum(np.abs(fc_comp1), np.abs(fc_comp2))/(np.abs(fc_comp1-fc_comp2)+1), -np.abs(fc_comp1-fc_comp2)/(np.maximum(np.abs(fc_comp1), np.abs(fc_comp2))+1))
def score(comp1_np, comp2_np):
    fc_comp1 = comp1_np[:,0]
    fc_comp2 = comp2_np[:,0]
    fdr_comp1_weight = weight(comp1_np[:,1])
    fdr_comp2_weight = weight(comp2_np[:,1])
    magnitude = np.abs(fc_comp1*fdr_comp1_weight) + np.abs(fdr_comp2_weight*fc_comp2)
    return np.array(magnitude * ratio(fc_comp1, fc_comp2))

def shuffle_calc(step, comp1_np, comp2_np):
    comp1_shuffle = sklearn.utils.shuffle(comp1_np, random_state=step)
    comp2_shuffle = sklearn.utils.shuffle(comp2_np, random_state=step+40000)
    permutation_score = score(comp1_shuffle, comp2_shuffle)
    return permutation_score

def calc_score():
    comp1 = pd.read_csv(comp1_file, sep='\t', decimal='.')
    comp2 = pd.read_csv(comp2_file, sep='\t', decimal='.')
    comp1 = comp1.dropna()
    comp2 = comp2.dropna()
    rows_keep = np.intersect1d(comp1[gname], comp2[gname])
## same genes and same order
    comp1 = comp1[comp1[gname].isin(rows_keep)]
    comp2 = comp2[comp2[gname].isin(rows_keep)]
## order dataframes by gname
    comp1 = comp1.sort_values(gname).reset_index(drop=True)
    comp2 = comp2.sort_values(gname).reset_index(drop=True)
    comp1[effect].astype(float)
    comp2[effect].astype(float)
    comp1[fdr].astype(float)
    comp2[fdr].astype(float)
    comp1_np = comp1[[effect, fdr]].to_numpy(dtype=float)
    comp2_np = comp2[[effect, fdr]].to_numpy(dtype=float)
    scores = np.array(score(comp1_np, comp2_np))
        ## filter with score not equal to 0
        ## filter comp1 and comp2 dataframe rows
        # filter_cond = (scores!=0) & ((comp1[fdr]<0.05) | (comp2[fdr]<0.05))
    filter_cond = scores!=0
        # print(sum(filter_cond))
    comp1 = comp1.loc[filter_cond]
    comp2 = comp2.loc[filter_cond]
    comp1_np = comp1_np[filter_cond]
    comp2_np = comp2_np[filter_cond]
    scores_notzero = scores[filter_cond]
        # scores_notzero = scores
## calculate permutatoin scores
    comp1_shuffles = []
    comp2_shuffles = []
## TODO: can also rewrite to yield
## if len(genes) < 200, k = len(genes)**2, else k = 40000
    if comp1_np.shape[0] < 200:
        k = comp1_np.shape[0]**2
    else:
        k = 40000
    pool = multiprocessing.Pool(64)
    permutation_scores = np.vstack(pool.starmap(shuffle_calc, zip(range(0, int(k)), repeat(comp1_np), repeat(comp2_np))))
    scores_all = np.vstack((scores_notzero, permutation_scores))
## the p-value is the proportion of the permutation scores that are more extreme than the original score
## these fcomp2lowing calculation should be row-wise
## for the scores array, if the first ccomp2umn is positive, then the p-value is the proportion of the permutation scores that are greater than the original score
## if the first ccomp2umn is negative, then the p-value is the proportion of the permutation scores that are less than the original score
    ps = np.ones(scores_all.shape[1], dtype = float)
    sense = []
    for i in range(scores_all.shape[1]):
        ps_tmp = float(np.sum(scores_all[1:, i] > scores_all[0, i]))/float((scores_all.shape[0]-1))
        if ps_tmp < 0.5:
            sense.append('high')
            ps[i] = ps_tmp
        else:
            sense.append('low')
            ps[i] = 1-ps_tmp
        # if scores_all[0, i] > 0:
        #     ps_tmp = float(np.sum(scores_all[1:, i] > scores_all[0, i]))/float((scores_all.shape[0]-1))
        #     sense.append('high')
        #     ps[i] = ps_tmp
        # else:
        #     ps_tmp = float(np.sum(scores_all[1:, i] < scores_all[0, i]))/float((scores_all.shape[0]-1))
        #     sense.append('low')
        #     ps[i] = ps_tmp            
    score_p = np.vstack((scores_all[0, :], ps))
## merge comp1 and comp2 by gname
    df_comp1_comp2 = pd.merge(comp1, comp2, on=gname, suffixes=('_comp1', '_comp2'))
    df_comp1_comp2 = df_comp1_comp2.sort_values(gname).reset_index(drop=True)
    df_comp1_comp2['score'] = score_p[0, :]
    df_comp1_comp2['p'] = score_p[1, :]
    df_comp1_comp2['convergence'] = sense
## get annotation whether the gene is coding or non-coding
## df where gname is in pc_gene_set, the coding is True, else False
    if mode == 'gene':
        df_comp1_comp2['coding'] = df_comp1_comp2[gname].isin(pc_gene_set)

    df_comp1_comp2.to_csv(output_file, index=False, float_format="%.64f", sep='\t')


if __name__ == '__main__':
    calc_score()
