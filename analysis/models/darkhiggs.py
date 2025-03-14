from __future__ import print_function, division
from optparse import OptionParser
from collections import defaultdict, OrderedDict
import concurrent.futures
import sys
import os
import rhalphalib as rl
import numpy as np
import pickle
import gzip
import json
from coffea import hist, processor
from coffea.util import load, save
from scipy import stats
import ROOT

rl.util.install_roofit_helpers()
rl.ParametericSample.PreferRooParametricHist = False

mass_binning = [40., 50., 60., 70., 80., 90., 100., 120., 150., 180., 240., 300.,]
recoil_binning = [250., 310., 370., 470., 590., 3000.]
category_map = {"pass": 1, "fail": 0}

def template(dictionary, process, systematic, recoil, region, category, min_value=1e-5, read_sumw2=False):
    histogram = dictionary[region].integrate("process", process)
    nominal, sumw2 = histogram.integrate("systematic", "nominal").values(sumw2=True)[()]
    nominal=nominal[recoil, :, category_map[category]]
    sumw2=sumw2[recoil, :, category_map[category]]
    zerobins = nominal <= 0.
    output = nominal
    if "data" not in systematic:
        output[zerobins] = min_value
        sumw2[zerobins] = 0.
    if "nominal" not in systematic and "data" not in systematic:
        output = histogram.integrate("systematic", systematic).values()[()][recoil, :, category_map[category]]
        output[zerobins] = 1.
        output[~zerobins] /= nominal[~zerobins]
        output[~zerobins] = np.maximum(output[~zerobins], 1e-5)
        output[np.isnan(output)] = 1.
    binning = (
        dictionary[region]
        .integrate("process", process)
        .integrate("systematic", systematic)
        .axis("fjmass")
        .edges()
    )
    if read_sumw2:
        return (output, binning, "fjmass", sumw2)
    return (output, binning, "fjmass")

def remap_histograms(hists):
    data_hists = {}
    bkg_hists = {}
    signal_hists = {}
    fakedata_map = OrderedDict()
  
    process = hist.Cat("process", "Process", sorting="placement")
    cats = ("process",)
    sig_map = OrderedDict()
    bkg_map = OrderedDict()
    data_map = OrderedDict()
    bkg_map["Hbb"] = ("Hbb*",)
    bkg_map["DY+jets"] = ("DY+*",)
    bkg_map["VV"] = (["WW", "WZ", "ZZ"],)
    bkg_map["ST"] = ("ST*",)
    bkg_map["TT"] = ("TT*",)
    bkg_map["W+jets"] = ("W+*",)
    bkg_map["W+HF"] = ("W+HF",)
    bkg_map["W+LF"] = ("W+LF",)
    bkg_map["Z+jets"] = ("Z+*",)
    bkg_map["Z+HF"] = ("Z+HF",)
    bkg_map["Z+LF"] = ("Z+LF",)
    bkg_map["G+jets"] = ("G+*",)
    bkg_map["QCD"] = ("QCD*",)
    data_map["MET"] = ("MET",)
    data_map["SingleElectron"] = ("SingleElectron",)
    data_map["SinglePhoton"] = ("SinglePhoton",)
    data_map["EGamma"] = ("EGamma",)
    
    for signal in hists['sig']['template'].identifiers('process'):
        if 'mhs' not in str(signal): continue
        sig_map[str(signal)] = (str(signal),)  ## signals
        
    fakedata_list = []
    for bkg in hists['bkg']['template'].identifiers('process'):
        fakedata_list.append(str(bkg))
    fakedata_map['FakeData'] = (fakedata_list,)
    
    for key in hists["data"].keys():
        bkg_hists[key] = hists["bkg"][key].group(cats, process, bkg_map)
        signal_hists[key] = hists["sig"][key].group(cats, process, sig_map)
        data_hists[key] = hists["data"][key].group(cats, process, data_map)
        data_hists[key] += hists["bkg"][key].group(cats, process, fakedata_map)
    
    bkg_hists["template"] = bkg_hists["template"].rebin(
        "fjmass", hist.Bin("fjmass", "Mass", mass_binning)
    )
    signal_hists["template"] = signal_hists["template"].rebin(
        "fjmass", hist.Bin("fjmass", "Mass", mass_binning)
    )
    data_hists["template"] = data_hists["template"].rebin(
        "fjmass", hist.Bin("fjmass", "Mass", mass_binning)
    )

    bkg_hists["template"] = bkg_hists["template"].rebin(
        "recoil", hist.Bin("recoil", "Recoil", recoil_binning)
    )
    signal_hists["template"] = signal_hists["template"].rebin(
        "recoil", hist.Bin("recoil", "Recoil", recoil_binning)
    )
    data_hists["template"] = data_hists["template"].rebin(
        "recoil", hist.Bin("recoil", "Recoil", recoil_binning)
    )

    hists = {"bkg": bkg_hists, "sig": signal_hists, "data": data_hists}

    return hists

'''
def get_mergedMC_stat_variations(dictionary, recoil, region, category, bkg_list):
    MCbkg = {}
    MCbkg_map = OrderedDict()
    process = hist.Cat("process", "Process", sorting="placement")
    cats = ("process",)
    for bkg in bkg_list:
        MCbkg_map[bkg] = (bkg,)
    MCbkg=dictionary[region].group(cats, process, MCbkg_map)
    merged_obj = MCbkg.integrate("process")
    merged_central, merged_error2 = merged_obj.integrate("systematic", "nominal").values(sumw2=True)[()]
    merged_central=merged_central[recoil, :, category_map[category]]
    merged_error2=merged_error2[recoil, :, category_map[category]]

    return merged_central, merged_error2
'''
def get_mergedMC_stat_variations(dictionary, recoil, region, category, bkg_list):
    templ=template(dictionary, bkg_list[0], "nominal", recoil, region, category, read_sumw2=True)
    merged_central=np.zeros_like(templ[0])
    merged_error2=np.zeros_like(templ[3])
    for bkg in bkg_list:
        templ=template(dictionary, bkg, "nominal", recoil, region, category, read_sumw2=True)
        for i in range(len(templ[0])):
            if templ[0][i] <= 1e-5 or templ[3][i] <= 0.:
                continue
            merged_central[i] += templ[0][i]
            merged_error2[i]  += templ[3][i]
    return merged_central, merged_error2

def addBBliteSyst(templ, param, merged_central, merged_error2, epsilon=0):
    for i in range(templ.observable.nbins):
        if merged_central[i] <= 0. or merged_error2[i] <= 0.:
            continue
        if templ._nominal[i] <= 1e-5:
            continue
        effect_up = np.ones_like(templ._nominal)
        effect_down = np.ones_like(templ._nominal)
        effect_up[i] = 1.0 + np.sqrt(merged_error2[i])/merged_central[i]
        effect_down[i] = max(epsilon, 1.0 - np.sqrt(merged_error2[i])/merged_central[i])
        templ.setParamEffect(param[i], effect_up, effect_down)

def addBtagSyst(dictionary, recoil, process, region, templ, category):
    btagUp = template(dictionary, process, "btagUp", recoil, region, category)[0]
    btagDown = template(dictionary, process, "btagDown", recoil, region, category)[0]
    templ.setParamEffect(btag, btagUp, btagDown)

def addVJetsSyst(dictionary, recoil, process, region, templ, category):
    def addSyst(dictionary, recoil, process, region, templ, category, syst, string):
        histogram = dictionary[region].integrate("process", process)
        nominal=histogram.integrate("systematic", "nominal").values()[()][recoil, :, category_map[category]]
        up=histogram.integrate("systematic", string+"Up").values()[()][recoil, :, category_map[category]]
        down=histogram.integrate("systematic",string+"Down").values()[()][recoil, :, category_map[category]]
        systUp = np.array( up.sum() / nominal.sum() )
        systUp[np.isnan(systUp)] = 1.
        systUp = systUp.sum()
        templ.setParamEffect(syst, systUp)
    addSyst(dictionary, recoil, process, region, templ, category, ew1, "ew1")
    addSyst(dictionary, recoil, process, region, templ, category, ew2W, "ew2W")
    addSyst(dictionary, recoil, process, region, templ, category, ew2Z, "ew2Z")
    addSyst(dictionary, recoil, process, region, templ, category, ew3W, "ew3W")
    addSyst(dictionary, recoil, process, region, templ, category, ew3Z, "ew3Z")
    addSyst(dictionary, recoil, process, region, templ, category, mix, "mix")
    addSyst(dictionary, recoil, process, region, templ, category, qcd1, "qcd1")
    addSyst(dictionary, recoil, process, region, templ, category, qcd2, "qcd2")
    addSyst(dictionary, recoil, process, region, templ, category, qcd3, "qcd3")

def model(year, mass, recoil, category):

    model_id = year + category + "mass" + mass+ "recoil" + str(recoil)
    print(model_id)
    model = rl.Model(model_id)

    ###
    ###
    # Signal region
    ###
    ###

    ch_name = "sr" + model_id
    sr = rl.Channel(ch_name)
    model.addChannel(sr)

    ###
    # Add data distribution to the channel
    ###

    if category == 'pass' and options.fakedata:
        dataTemplate = template(data, "FakeData", "data", recoil, "sr", category)
    else:
        dataTemplate = template(data, "MET", "data", recoil, "sr", category)
    sr.setObservation(dataTemplate)

    ###
    # Z(->nunu)+jets data-driven model
    ###

    if category == "pass":
        sr_zjets = sr_zjetsPass
    else:
        sr_zjets = sr_zjetsFail
    sr.addSample(sr_zjets)

    ###
    # W(->lnu)+jets data-driven model
    ###

    if not iswjetsMC:
        if category == "pass":
            sr_wjets = sr_wjetsPass
            sr_wjetsMC = sr_wjetsMCPass
        else:
            sr_wjets = sr_wjetsFail
            sr_wjetsMC = sr_wjetsMCFail
        sr.addSample(sr_wjets)
        
    ###
    # top-antitop data-driven model
    ###

    if not isttMC:
        sr_ttTemplate = template(background, "TT", "nominal", recoil, "sr", category, min_value=1., read_sumw2=True)
        sr_ttMC = rl.TemplateSample("sr" + model_id + "_ttMC",rl.Sample.BACKGROUND,sr_ttTemplate)
        sr_ttMC.setParamEffect(lumi, nlumi)
        sr_ttMC.setParamEffect(trig_met, ntrig_met)
        sr_ttMC.setParamEffect(veto_tau, nveto_tau)
        sr_ttMC.setParamEffect(jec, njec)
        sr_ttMC.setParamEffect(ttMC_norm, nMinor_norm)
        sr_ttMC.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoil, "TT", "sr", sr_ttMC, category)

        sr_ttObservable = rl.Observable("fjmass", sr_ttTemplate[1])
        sr_ttBinYields = np.array([rl.IndependentParameter('tmp', b, 1e-5, sr_ttTemplate[0].max()*2) for b in sr_ttTemplate[0]])
        sr_tt = rl.ParametericSample(ch_name + "_tt", rl.Sample.BACKGROUND, sr_ttObservable, sr_ttBinYields)
        sr.addSample(sr_tt)
    
    ###
    # Other MC-driven processes
    ###
    
    nbins = len(dataTemplate[1]) - 1
    param = [None for _ in range(nbins)]
    for i in range(nbins):
        param[i] = rl.NuisanceParameter(ch_name + '_mcstat_bin%i' % i, combinePrior='shape')

    MCbkgList = ["ST", "DY+jets", "VV", "Hbb", "QCD"]
    if isttMC: MCbkgList.append("TT")
    if iswjetsMC: MCbkgList.append("W+jets")
    sr_central, sr_error2 = get_mergedMC_stat_variations(background, recoil, "sr", category, MCbkgList)

    if iswjetsMC: 
        sr_wjetsTemplate = template(background, "W+jets", "nominal", recoil, "sr", category, read_sumw2=True)
        sr_wjets = rl.TemplateSample( "sr" + model_id + "_wjetsMC", rl.Sample.BACKGROUND, sr_wjetsTemplate)
        sr_wjets.setParamEffect(lumi, nlumi)
        sr_wjets.setParamEffect(trig_met, ntrig_met)
        sr_wjets.setParamEffect(veto_tau, nveto_tau)
        sr_wjets.setParamEffect(wjetsMC_norm, nVjets_norm)
        sr_wjets.setParamEffect(jec, njec)
        addBBliteSyst(sr_wjets, param, sr_central, sr_error2, epsilon=1e-5) ### replace autoMCStats
        addBtagSyst(background, recoil, "W+jets", "sr", sr_wjets, category)
        addVJetsSyst(background, recoil, "W+jets", "sr", sr_wjets, category)
        sr.addSample(sr_wjets)

    if isttMC: 
        sr_ttTemplate = template(background, "TT", "nominal", recoil, "sr", category, read_sumw2=True)
        sr_tt = rl.TemplateSample("sr" + model_id + "_ttMC",rl.Sample.BACKGROUND,sr_ttTemplate)
        sr_tt.setParamEffect(lumi, nlumi)
        sr_tt.setParamEffect(trig_met, ntrig_met)
        sr_tt.setParamEffect(veto_tau, nveto_tau)
        sr_tt.setParamEffect(jec, njec)
        sr_tt.setParamEffect(ttMC_norm, nMinor_norm) ### ttMC should be applied for SR fail
        addBtagSyst(background, recoil, "TT", "sr", sr_tt, category)
        addBBliteSyst(sr_tt, param, sr_central, sr_error2, epsilon=1e-5) ### replace autoMCStats
        sr.addSample(sr_tt)
    
    sr_stTemplate = template(background, "ST", "nominal", recoil, "sr", category, read_sumw2=True)
    sr_st = rl.TemplateSample(ch_name + "_stMC", rl.Sample.BACKGROUND, sr_stTemplate)
    sr_st.setParamEffect(lumi, nlumi)
    sr_st.setParamEffect(trig_met, ntrig_met)
    sr_st.setParamEffect(veto_tau, nveto_tau)
    sr_st.setParamEffect(st_norm, nMinor_norm)
    sr_st.setParamEffect(jec, njec)
    addBBliteSyst(sr_st, param, sr_central, sr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoil, "ST", "sr", sr_st, category)
    sr.addSample(sr_st)

    sr_dyjetsTemplate = template(background, "DY+jets", "nominal", recoil, "sr", category, read_sumw2=True)
    sr_dyjets = rl.TemplateSample(
        ch_name + "_dyjetsMC", rl.Sample.BACKGROUND, sr_dyjetsTemplate
    )
    sr_dyjets.setParamEffect(lumi, nlumi)
    sr_dyjets.setParamEffect(trig_met, ntrig_met)
    sr_dyjets.setParamEffect(veto_tau, nveto_tau)
    sr_dyjets.setParamEffect(zjetsMC_norm, nVjets_norm)
    sr_dyjets.setParamEffect(jec, njec)
    addBBliteSyst(sr_dyjets, param, sr_central, sr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoil, "DY+jets", "sr", sr_dyjets, category)
    addVJetsSyst(background, recoil, "DY+jets", "sr", sr_dyjets, category)
    sr.addSample(sr_dyjets)

    sr_vvTemplate = template(background, "VV", "nominal", recoil, "sr", category, read_sumw2=True)
    sr_vv = rl.TemplateSample(ch_name + "_vvMC", rl.Sample.BACKGROUND, sr_vvTemplate)
    sr_vv.setParamEffect(lumi, nlumi)
    sr_vv.setParamEffect(trig_met, ntrig_met)
    sr_vv.setParamEffect(veto_tau, nveto_tau)
    sr_vv.setParamEffect(vv_norm, nMinor_norm)
    sr_vv.setParamEffect(jec, njec)
    addBBliteSyst(sr_vv, param, sr_central, sr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoil, "VV", "sr", sr_vv, category)
    sr.addSample(sr_vv)

    sr_hbbTemplate = template(background, "Hbb", "nominal", recoil, "sr", category, read_sumw2=True)
    sr_hbb = rl.TemplateSample(ch_name + "_hbbMC", rl.Sample.BACKGROUND, sr_hbbTemplate)
    sr_hbb.setParamEffect(lumi, nlumi)
    sr_hbb.setParamEffect(trig_met, ntrig_met)
    sr_hbb.setParamEffect(veto_tau, nveto_tau)
    sr_hbb.setParamEffect(hbb_norm, nMinor_norm)
    sr_hbb.setParamEffect(jec, njec)
    addBBliteSyst(sr_hbb, param, sr_central, sr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoil, "Hbb", "sr", sr_hbb, category)
    sr.addSample(sr_hbb)

    sr_qcdTemplate = template(background, "QCD", "nominal", recoil, "sr", category, read_sumw2=True)
    sr_qcd = rl.TemplateSample(ch_name + "_qcdMC", rl.Sample.BACKGROUND, sr_qcdTemplate)
    sr_qcd.setParamEffect(lumi, nlumi)
    sr_qcd.setParamEffect(trig_met, ntrig_met)
    sr_qcd.setParamEffect(veto_tau, nveto_tau)
    sr_qcd.setParamEffect(qcdsig_norm, nqcd_norm)
    sr_qcd.setParamEffect(jec, njec)
    addBBliteSyst(sr_qcd, param, sr_central, sr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoil, "QCD", "sr", sr_qcd, category)
    sr.addSample(sr_qcd)

    for s in signal["sr"].identifiers("process"):
        sr_signalTemplate = template(signal, s, "nominal", recoil, "sr", category, read_sumw2=True)
        sr_signal = rl.TemplateSample(ch_name + "_" + str(s), rl.Sample.SIGNAL, sr_signalTemplate)
        sr_signal.setParamEffect(lumi, nlumi)
        sr_signal.setParamEffect(trig_met, ntrig_met)
        sr_signal.setParamEffect(veto_tau, nveto_tau)
        sr_signal.setParamEffect(jec, njec)
        #sr_signal.autoMCStats(epsilon=1e-5)
        for i in range(sr_signal.observable.nbins):
            if sr_signal._nominal[i] <= 0. or sr_signal._sumw2[i] <= 0.:
                continue
            effect_up = np.ones_like(sr_signal._nominal)
            effect_down = np.ones_like(sr_signal._nominal)
            effect_up[i] = (sr_signal._nominal[i] + np.sqrt(sr_signal._sumw2[i]))/sr_signal._nominal[i]
            effect_down[i] = max((sr_signal._nominal[i] - np.sqrt(sr_signal._sumw2[i]))/sr_signal._nominal[i], 1e-5)
            param = rl.NuisanceParameter(str(s) + "_" + ch_name + '_mcstat_bin%i' % i, combinePrior='shape')
            sr_signal.setParamEffect(param, effect_up, effect_down)
        addBtagSyst(signal, recoil, str(s), "sr", sr_signal, category)
        if category=="pass": sr.addSample(sr_signal)

    ###
    # End of SR
    ###

    ###
    ###
    # Single muon W control region
    ###
    ###

    ch_name = "wmcr" + model_id
    wmcr = rl.Channel(ch_name)
    model.addChannel(wmcr)

    ###
    # Add data distribution to the channel
    ###

    dataTemplate = template(data, "MET", "data", recoil, "wmcr", category)
    wmcr.setObservation(dataTemplate)

    ###
    # W(->lnu)+jets data-driven model
    ###

    if not iswjetsMC:
        wmcr_wjetsTemplate = template(background, "W+jets", "nominal", recoil, "wmcr", category, min_value=1., read_sumw2=True)
        wmcr_wjetsMC = rl.TemplateSample("wmcr" + model_id + "_wjetsMC", rl.Sample.BACKGROUND, wmcr_wjetsTemplate)
        wmcr_wjetsMC.setParamEffect(lumi, nlumi)
        wmcr_wjetsMC.setParamEffect(trig_met, ntrig_met)
        wmcr_wjetsMC.setParamEffect(veto_tau, nveto_tau)
        wmcr_wjetsMC.setParamEffect(wjets_norm, nVjets_norm)
        wmcr_wjetsMC.setParamEffect(jec, njec)
        wmcr_wjetsMC.setParamEffect(id_mu, nlepton)
        wmcr_wjetsMC.setParamEffect(iso_mu, nlepton)
        wmcr_wjetsMC.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoil, "W+jets", "wmcr", wmcr_wjetsMC, category)
        addVJetsSyst(background, recoil, "W+jets", "wmcr", wmcr_wjetsMC, category)

        #### Transfer Factor
        wmcr_wjetsTransferFactor = wmcr_wjetsMC.getExpectation() / sr_wjetsMC.getExpectation()
        wmcr_wjets = rl.TransferFactorSample(ch_name + "_wjets", rl.Sample.BACKGROUND, wmcr_wjetsTransferFactor, sr_wjets)
        wmcr.addSample(wmcr_wjets)

    ###
    # top-antitop data-driven model
    ###

    if not isttMC:
        wmcr_ttTemplate = template(background, "TT", "nominal", recoil, "wmcr", category, min_value=1., read_sumw2=True)
        wmcr_ttMC = rl.TemplateSample( "wmcr" + model_id + "_ttMC", rl.Sample.BACKGROUND, wmcr_ttTemplate)
        wmcr_ttMC.setParamEffect(lumi, nlumi)
        wmcr_ttMC.setParamEffect(trig_met, ntrig_met)
        wmcr_ttMC.setParamEffect(veto_tau, nveto_tau)
        wmcr_ttMC.setParamEffect(jec, njec)
        wmcr_ttMC.setParamEffect(id_mu, nlepton)
        wmcr_ttMC.setParamEffect(iso_mu, nlepton)
        wmcr_ttMC.setParamEffect(ttMC_norm, nMinor_norm)
        wmcr_ttMC.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoil, "TT", "wmcr", wmcr_ttMC, category)

        #### Transfer Factor
        wmcr_ttTransferFactor = wmcr_ttMC.getExpectation() / sr_ttMC.getExpectation()
        wmcr_tt = rl.TransferFactorSample(ch_name + "_tt", rl.Sample.BACKGROUND, wmcr_ttTransferFactor, sr_tt)
        wmcr.addSample(wmcr_tt)
    
    ###
    # Other MC-driven processes
    ###

    nbins = len(dataTemplate[1]) - 1
    param = [None for _ in range(nbins)]
    for i in range(nbins):
        param[i] = rl.NuisanceParameter(ch_name + '_mcstat_bin%i' % i, combinePrior='shape')

    MCbkgList = ["ST", "DY+jets", "VV", "Hbb", "QCD"]
    if isttMC: MCbkgList.append("TT")
    if iswjetsMC: MCbkgList.append("W+jets")
    wmcr_central, wmcr_error2 = get_mergedMC_stat_variations(background, recoil, "wmcr", category, MCbkgList)
    
    if iswjetsMC:
        wmcr_wjetsTemplate = template(background, "W+jets", "nominal", recoil, "wmcr", category, min_value=1., read_sumw2=True)
        wmcr_wjets = rl.TemplateSample("wmcr" + model_id + "_wjetsMC", rl.Sample.BACKGROUND, wmcr_wjetsTemplate)
        wmcr_wjets.setParamEffect(lumi, nlumi)
        wmcr_wjets.setParamEffect(trig_met, ntrig_met)
        wmcr_wjets.setParamEffect(veto_tau, nveto_tau)
        wmcr_wjets.setParamEffect(wjetsMC_norm, nVjets_norm)
        wmcr_wjets.setParamEffect(jec, njec)
        wmcr_wjets.setParamEffect(id_mu, nlepton)
        wmcr_wjets.setParamEffect(iso_mu, nlepton)
        addBBliteSyst(wmcr_wjets, param, wmcr_central, wmcr_error2, epsilon=1e-5)
        addBtagSyst(background, recoil, "W+jets", "wmcr", wmcr_wjets, category)
        addVJetsSyst(background, recoil, "W+jets", "wmcr", wmcr_wjets, category)
        wmcr.addSample(wmcr_wjets)

    if isttMC: 
        wmcr_ttTemplate = template(background, "TT", "nominal", recoil, "wmcr", category, read_sumw2=True)
        wmcr_tt = rl.TemplateSample( "wmcr" + model_id + "_ttMC", rl.Sample.BACKGROUND, wmcr_ttTemplate)
        wmcr_tt.setParamEffect(lumi, nlumi)
        wmcr_tt.setParamEffect(trig_met, ntrig_met)
        wmcr_tt.setParamEffect(veto_tau, nveto_tau)
        wmcr_tt.setParamEffect(jec, njec)
        wmcr_tt.setParamEffect(id_mu, nlepton)
        wmcr_tt.setParamEffect(iso_mu, nlepton)
        wmcr_tt.setParamEffect(ttMC_norm, nMinor_norm)
        addBtagSyst(background, recoil, "TT", "wmcr", wmcr_tt, category)
        addBBliteSyst(wmcr_tt, param, wmcr_central, wmcr_error2, epsilon=1e-5) ### replace autoMCStats
        wmcr.addSample(wmcr_tt)
                    
    wmcr_stTemplate = template(background, "ST", "nominal", recoil, "wmcr", category, read_sumw2=True)
    wmcr_st = rl.TemplateSample(ch_name + "_stMC", rl.Sample.BACKGROUND, wmcr_stTemplate)
    wmcr_st.setParamEffect(lumi, nlumi)
    wmcr_st.setParamEffect(trig_met, ntrig_met)
    wmcr_st.setParamEffect(veto_tau, nveto_tau)
    wmcr_st.setParamEffect(st_norm, nMinor_norm)
    wmcr_st.setParamEffect(jec, njec)
    wmcr_st.setParamEffect(id_mu, nlepton)
    wmcr_st.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(wmcr_st, param, wmcr_central, wmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "ST", "wmcr", wmcr_st, category)
    wmcr.addSample(wmcr_st)

    wmcr_dyjetsTemplate = template(background, "DY+jets", "nominal", recoil, "wmcr", category, read_sumw2=True)
    wmcr_dyjets = rl.TemplateSample(ch_name + "_dyjetsMC", rl.Sample.BACKGROUND, wmcr_dyjetsTemplate)
    wmcr_dyjets.setParamEffect(lumi, nlumi)
    wmcr_dyjets.setParamEffect(trig_met, ntrig_met)
    wmcr_dyjets.setParamEffect(veto_tau, nveto_tau)
    wmcr_dyjets.setParamEffect(zjetsMC_norm, nVjets_norm)
    wmcr_dyjets.setParamEffect(jec, njec)
    wmcr_dyjets.setParamEffect(id_mu, nlepton)
    wmcr_dyjets.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(wmcr_dyjets, param, wmcr_central, wmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "DY+jets", "wmcr", wmcr_dyjets, category)
    addVJetsSyst(background, recoil, "DY+jets", "wmcr", wmcr_dyjets, category)
    wmcr.addSample(wmcr_dyjets)

    wmcr_vvTemplate = template(background, "VV", "nominal", recoil, "wmcr", category, read_sumw2=True)
    wmcr_vv = rl.TemplateSample(ch_name + "_vvMC", rl.Sample.BACKGROUND, wmcr_vvTemplate)
    wmcr_vv.setParamEffect(lumi, nlumi)
    wmcr_vv.setParamEffect(trig_met, ntrig_met)
    wmcr_vv.setParamEffect(veto_tau, nveto_tau)
    wmcr_vv.setParamEffect(vv_norm, nMinor_norm)
    wmcr_vv.setParamEffect(jec, njec)
    wmcr_vv.setParamEffect(id_mu, nlepton)
    wmcr_vv.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(wmcr_vv, param, wmcr_central, wmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "VV", "wmcr", wmcr_vv, category)
    wmcr.addSample(wmcr_vv)

    wmcr_hbbTemplate = template(background, "Hbb", "nominal", recoil, "wmcr", category, read_sumw2=True)
    wmcr_hbb = rl.TemplateSample(ch_name + "_hbbMC", rl.Sample.BACKGROUND, wmcr_hbbTemplate)
    wmcr_hbb.setParamEffect(lumi, nlumi)
    wmcr_hbb.setParamEffect(trig_met, ntrig_met)
    wmcr_hbb.setParamEffect(veto_tau, nveto_tau)
    wmcr_hbb.setParamEffect(hbb_norm, nMinor_norm)
    wmcr_hbb.setParamEffect(jec, njec)
    wmcr_hbb.setParamEffect(id_mu, nlepton)
    wmcr_hbb.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(wmcr_hbb, param, wmcr_central, wmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "Hbb", "wmcr", wmcr_hbb, category)
    wmcr.addSample(wmcr_hbb)

    wmcr_qcdTemplate = template(background, "QCD", "nominal", recoil, "wmcr", category, read_sumw2=True)
    wmcr_qcd = rl.TemplateSample(ch_name + "_qcdMC", rl.Sample.BACKGROUND, wmcr_qcdTemplate)
    wmcr_qcd.setParamEffect(lumi, nlumi)
    wmcr_qcd.setParamEffect(trig_met, ntrig_met)
    wmcr_qcd.setParamEffect(veto_tau, nveto_tau)
    wmcr_qcd.setParamEffect(qcdmu_norm, nqcd_norm)
    wmcr_qcd.setParamEffect(jec, njec)
    wmcr_qcd.setParamEffect(id_mu, nlepton)
    wmcr_qcd.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(wmcr_qcd, param, wmcr_central, wmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "QCD", "wmcr", wmcr_qcd, category)
    wmcr.addSample(wmcr_qcd)

    ###
    # End of single muon W control region
    ###

    ###
    ###
    # Single electron W control region
    ###
    ###

    ch_name = "wecr" + model_id
    wecr = rl.Channel(ch_name)
    model.addChannel(wecr)

    ###
    # Add data distribution to the channel
    ###

    if year == "2018":
        dataTemplate = template(data, "EGamma", "data", recoil, "wecr", category)
    else:
        dataTemplate = template(data, "SingleElectron", "data", recoil, "wecr", category)
    wecr.setObservation(dataTemplate)

    ###
    # W(->lnu)+jets data-driven model
    ###

    if not iswjetsMC:
        wecr_wjetsTemplate = template(background, "W+jets", "nominal", recoil, "wecr", category, min_value=1., read_sumw2=True)
        wecr_wjetsMC = rl.TemplateSample("wecr" + model_id + "_wjetsMC", rl.Sample.BACKGROUND, wecr_wjetsTemplate)
        wecr_wjetsMC.setParamEffect(lumi, nlumi)
        wecr_wjetsMC.setParamEffect(trig_e, ntrig_e)
        wecr_wjetsMC.setParamEffect(veto_tau, nveto_tau)
        wecr_wjetsMC.setParamEffect(wjets_norm, nVjets_norm)
        wecr_wjetsMC.setParamEffect(jec, njec)
        wecr_wjetsMC.setParamEffect(id_e, nlepton)
        wecr_wjetsMC.setParamEffect(reco_e, nlepton)
        wecr_wjetsMC.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoil, "W+jets", "wecr", wecr_wjetsMC, category)
        addVJetsSyst(background, recoil, "W+jets", "wecr", wecr_wjetsMC, category)

        #### Transfer Factor
        wecr_wjetsTransferFactor = wecr_wjetsMC.getExpectation() / sr_wjetsMC.getExpectation()
        wecr_wjets = rl.TransferFactorSample( ch_name + "_wjets", rl.Sample.BACKGROUND, wecr_wjetsTransferFactor, sr_wjets)
        wecr.addSample(wecr_wjets)

    ###
    # top-antitop data-driven model
    ###

    if not isttMC: 
        wecr_ttTemplate = template(background, "TT", "nominal", recoil, "wecr", category, min_value=1., read_sumw2=True)
        wecr_ttMC = rl.TemplateSample("wecr" + model_id + "_ttMC", rl.Sample.BACKGROUND, wecr_ttTemplate)
        wecr_ttMC.setParamEffect(lumi, nlumi)
        wecr_ttMC.setParamEffect(trig_e, ntrig_e)
        wecr_ttMC.setParamEffect(veto_tau, nveto_tau)
        wecr_ttMC.setParamEffect(jec, njec)
        wecr_ttMC.setParamEffect(id_e, nlepton)
        wecr_ttMC.setParamEffect(reco_e, nlepton)
        wecr_ttMC.setParamEffect(ttMC_norm, nMinor_norm)
        wecr_ttMC.autoMCStats(epsilon=1e-5) ### autoMCStats is used for transferfactorsample
        addBtagSyst(background, recoil, "TT", "wecr", wecr_ttMC, category)

        #### Transfer Factor
        wecr_ttTransferFactor = wecr_ttMC.getExpectation() / sr_ttMC.getExpectation()
        wecr_tt = rl.TransferFactorSample( ch_name + "_tt", rl.Sample.BACKGROUND, wecr_ttTransferFactor, sr_tt)
        wecr.addSample(wecr_tt)
    
    ###
    # Other MC-driven processes
    ###

    nbins = len(dataTemplate[1]) - 1
    param = [None for _ in range(nbins)]
    for i in range(nbins):
        param[i] = rl.NuisanceParameter(ch_name + '_mcstat_bin%i' % i, combinePrior='shape')

    MCbkgList = ["ST", "DY+jets", "VV", "Hbb", "QCD"]
    if isttMC: MCbkgList.append("TT")
    if iswjetsMC: MCbkgList.append("W+jets")
    wecr_central, wecr_error2 = get_mergedMC_stat_variations(background, recoil, "wecr", category, MCbkgList)

    if iswjetsMC:
        wecr_wjetsTemplate = template(background, "W+jets", "nominal", recoil, "wecr", category, min_value=1., read_sumw2=True)
        wecr_wjets = rl.TemplateSample("wecr" + model_id + "_wjetsMC", rl.Sample.BACKGROUND, wecr_wjetsTemplate)
        wecr_wjets.setParamEffect(lumi, nlumi)
        wecr_wjets.setParamEffect(trig_e, ntrig_e)
        wecr_wjets.setParamEffect(veto_tau, nveto_tau)
        wecr_wjets.setParamEffect(wjetsMC_norm, nVjets_norm)
        wecr_wjets.setParamEffect(jec, njec)
        wecr_wjets.setParamEffect(id_e, nlepton)
        wecr_wjets.setParamEffect(reco_e, nlepton)
        addBBliteSyst(wecr_wjets, param, wecr_central, wecr_error2, epsilon=1e-5) ### replace autoMCStats
        addBtagSyst(background, recoil, "W+jets", "wecr", wecr_wjets, category)
        addVJetsSyst(background, recoil, "W+jets", "wecr", wecr_wjets, category)
        wecr.addSample(wecr_wjets)

    if isttMC: 
        wecr_ttTemplate = template(background, "TT", "nominal", recoil, "wecr", category, read_sumw2=True)
        wecr_tt = rl.TemplateSample("wecr" + model_id + "_ttMC", rl.Sample.BACKGROUND, wecr_ttTemplate)
        wecr_tt.setParamEffect(lumi, nlumi)
        wecr_tt.setParamEffect(trig_e, ntrig_e)
        wecr_tt.setParamEffect(veto_tau, nveto_tau)
        wecr_tt.setParamEffect(jec, njec)
        wecr_tt.setParamEffect(id_e, nlepton)
        wecr_tt.setParamEffect(reco_e, nlepton)
        wecr_tt.setParamEffect(ttMC_norm, nMinor_norm)
        addBBliteSyst(wecr_tt, param, wecr_central, wecr_error2, epsilon=1e-5) ### replace autoMCStats
        addBtagSyst(background, recoil, "TT", "wecr", wecr_tt, category)
        wecr.addSample(wecr_tt)

    wecr_stTemplate = template(background, "ST", "nominal", recoil, "wecr", category, read_sumw2=True)
    wecr_st = rl.TemplateSample(ch_name + "_stMC", rl.Sample.BACKGROUND, wecr_stTemplate)
    wecr_st.setParamEffect(lumi, nlumi)
    wecr_st.setParamEffect(trig_e, ntrig_e)
    wecr_st.setParamEffect(veto_tau, nveto_tau)
    wecr_st.setParamEffect(st_norm, nMinor_norm)
    wecr_st.setParamEffect(jec, njec)
    wecr_st.setParamEffect(id_e, nlepton)
    wecr_st.setParamEffect(reco_e, nlepton)
    addBBliteSyst(wecr_st, param, wecr_central, wecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "ST", "wecr", wecr_st, category)
    wecr.addSample(wecr_st)

    wecr_dyjetsTemplate = template(background, "DY+jets", "nominal", recoil, "wecr", category, read_sumw2=True)
    wecr_dyjets = rl.TemplateSample(ch_name + "_dyjetsMC", rl.Sample.BACKGROUND, wecr_dyjetsTemplate)
    wecr_dyjets.setParamEffect(lumi, nlumi)
    wecr_dyjets.setParamEffect(trig_e, ntrig_e)
    wecr_dyjets.setParamEffect(veto_tau, nveto_tau)
    wecr_dyjets.setParamEffect(zjetsMC_norm, nVjets_norm)
    wecr_dyjets.setParamEffect(jec, njec)
    wecr_dyjets.setParamEffect(id_e, nlepton)
    wecr_dyjets.setParamEffect(reco_e, nlepton)
    addBBliteSyst(wecr_dyjets, param, wecr_central, wecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "DY+jets", "wecr", wecr_dyjets, category)
    addVJetsSyst(background, recoil, "DY+jets", "wecr", wecr_dyjets, category)
    wecr.addSample(wecr_dyjets)

    wecr_vvTemplate = template(background, "VV", "nominal", recoil, "wecr", category, read_sumw2=True)
    wecr_vv = rl.TemplateSample(ch_name + "_vvMC", rl.Sample.BACKGROUND, wecr_vvTemplate)
    wecr_vv.setParamEffect(lumi, nlumi)
    wecr_vv.setParamEffect(trig_e, ntrig_e)
    wecr_vv.setParamEffect(veto_tau, nveto_tau)
    wecr_vv.setParamEffect(vv_norm, nMinor_norm)
    wecr_vv.setParamEffect(jec, njec)
    wecr_vv.setParamEffect(id_e, nlepton)
    wecr_vv.setParamEffect(reco_e, nlepton)
    addBBliteSyst(wecr_vv, param, wecr_central, wecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "VV", "wecr", wecr_vv, category)
    wecr.addSample(wecr_vv)

    wecr_hbbTemplate = template(background, "Hbb", "nominal", recoil, "wecr", category, read_sumw2=True)
    wecr_hbb = rl.TemplateSample(ch_name + "_hbbMC", rl.Sample.BACKGROUND, wecr_hbbTemplate)
    wecr_hbb.setParamEffect(lumi, nlumi)
    wecr_hbb.setParamEffect(trig_e, ntrig_e)
    wecr_hbb.setParamEffect(veto_tau, nveto_tau)
    wecr_hbb.setParamEffect(hbb_norm, nMinor_norm)
    wecr_hbb.setParamEffect(jec, njec)
    wecr_hbb.setParamEffect(id_e, nlepton)
    wecr_hbb.setParamEffect(reco_e, nlepton)
    addBBliteSyst(wecr_hbb, param, wecr_central, wecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "Hbb", "wecr", wecr_hbb, category)
    wecr.addSample(wecr_hbb)

    wecr_qcdTemplate = template(background, "QCD", "nominal", recoil, "wecr", category, read_sumw2=True)
    wecr_qcd = rl.TemplateSample(ch_name + "_qcdMC", rl.Sample.BACKGROUND, wecr_qcdTemplate)
    wecr_qcd.setParamEffect(lumi, nlumi)
    wecr_qcd.setParamEffect(trig_e, ntrig_e)
    wecr_qcd.setParamEffect(veto_tau, nveto_tau)
    wecr_qcd.setParamEffect(qcde_norm, nqcd_norm)
    wecr_qcd.setParamEffect(jec, njec)
    wecr_qcd.setParamEffect(id_e, nlepton)
    wecr_qcd.setParamEffect(reco_e, nlepton)
    addBBliteSyst(wecr_qcd, param, wecr_central, wecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "QCD", "wecr", wecr_qcd, category)
    wecr.addSample(wecr_qcd)

    ###
    # End of single electron W control region
    ###

    if category=="fail": return model

    ###
    ###
    # Single muon top control region
    ###
    ###

    ch_name = "tmcr" + model_id
    tmcr = rl.Channel(ch_name)
    model.addChannel(tmcr)

    ###
    # Add data distribution to the channel
    ###

    dataTemplate = template(data, "MET", "data", recoil, "tmcr", category)
    tmcr.setObservation(dataTemplate)

    ###
    # top-antitop data-driven model
    ###

    if not isttMC:
        tmcr_ttTemplate = template(background, "TT", "nominal", recoil, "tmcr", category, min_value=1., read_sumw2=True)
        tmcr_ttMC = rl.TemplateSample("tmcr" + model_id + "_ttMC", rl.Sample.BACKGROUND, tmcr_ttTemplate)
        tmcr_ttMC.setParamEffect(lumi, nlumi)
        tmcr_ttMC.setParamEffect(trig_met, ntrig_met)
        tmcr_ttMC.setParamEffect(veto_tau, nveto_tau)
        tmcr_ttMC.setParamEffect(ttMC_norm, nMinor_norm)
        tmcr_ttMC.setParamEffect(jec, njec)
        tmcr_ttMC.setParamEffect(id_mu, nlepton)
        tmcr_ttMC.setParamEffect(iso_mu, nlepton)
        tmcr_ttMC.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoil, "TT", "tmcr", tmcr_ttMC, category)

        #### Transfer Factor
        tmcr_ttTransferFactor = tmcr_ttMC.getExpectation() / sr_ttMC.getExpectation()
        tmcr_tt = rl.TransferFactorSample(ch_name + "_tt", rl.Sample.BACKGROUND, tmcr_ttTransferFactor, sr_tt)
        tmcr.addSample(tmcr_tt)

    ###
    # Other MC-driven processes
    ###

    nbins = len(dataTemplate[1]) - 1
    param = [None for _ in range(nbins)]
    for i in range(nbins):
        param[i] = rl.NuisanceParameter(ch_name + '_mcstat_bin%i' % i, combinePrior='shape')

    MCbkgList = ["ST", "DY+jets", "VV", "Hbb", "W+jets", "QCD"]
    if isttMC: MCbkgList.append("TT")
    tmcr_central, tmcr_error2 = get_mergedMC_stat_variations(background, recoil, "tmcr", category, MCbkgList)

    if isttMC:
        tmcr_ttTemplate = template(background, "TT", "nominal", recoil, "tmcr", category, min_value=1., read_sumw2=True)
        tmcr_tt = rl.TemplateSample("tmcr" + model_id + "_ttMC", rl.Sample.BACKGROUND, tmcr_ttTemplate)
        tmcr_tt.setParamEffect(lumi, nlumi)
        tmcr_tt.setParamEffect(trig_met, ntrig_met)
        tmcr_tt.setParamEffect(veto_tau, nveto_tau)
        tmcr_tt.setParamEffect(ttMC_norm, nMinor_norm)
        tmcr_tt.setParamEffect(jec, njec)
        tmcr_tt.setParamEffect(id_mu, nlepton)
        tmcr_tt.setParamEffect(iso_mu, nlepton)
        addBBliteSyst(tmcr_tt, param, tmcr_central, tmcr_error2, epsilon=1e-5)
        addBtagSyst(background, recoil, "TT", "tmcr", tmcr_tt, category)
        tmcr.addSample(tmcr_tt)

    tmcr_wjetsTemplate = template(background, "W+jets", "nominal", recoil, "tmcr", category, read_sumw2=True)
    tmcr_wjets = rl.TemplateSample(ch_name + "_wjetsMC", rl.Sample.BACKGROUND, tmcr_wjetsTemplate)
    tmcr_wjets.setParamEffect(lumi, nlumi)
    tmcr_wjets.setParamEffect(trig_met, ntrig_met)
    tmcr_wjets.setParamEffect(veto_tau, nveto_tau)
    tmcr_wjets.setParamEffect(wjetsMC_norm, nVjets_norm)
    tmcr_wjets.setParamEffect(jec, njec)
    tmcr_wjets.setParamEffect(id_mu, nlepton)
    tmcr_wjets.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(tmcr_wjets, param, tmcr_central, tmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "W+jets", "tmcr", tmcr_wjets, category)
    addVJetsSyst(background, recoil, "W+jets", "tmcr", tmcr_wjets, category)
    tmcr.addSample(tmcr_wjets)

    tmcr_stTemplate = template(background, "ST", "nominal", recoil, "tmcr", category, read_sumw2=True)
    tmcr_st = rl.TemplateSample(ch_name + "_stMC", rl.Sample.BACKGROUND, tmcr_stTemplate)
    tmcr_st.setParamEffect(lumi, nlumi)
    tmcr_st.setParamEffect(trig_met, ntrig_met)
    tmcr_st.setParamEffect(veto_tau, nveto_tau)
    tmcr_st.setParamEffect(st_norm, nMinor_norm)
    tmcr_st.setParamEffect(jec, njec)
    tmcr_st.setParamEffect(id_mu, nlepton)
    tmcr_st.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(tmcr_st, param, tmcr_central, tmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "ST", "tmcr", tmcr_st, category)
    tmcr.addSample(tmcr_st)

    tmcr_dyjetsTemplate = template(background, "DY+jets", "nominal", recoil, "tmcr", category, read_sumw2=True)
    tmcr_dyjets = rl.TemplateSample(ch_name + "_dyjetsMC", rl.Sample.BACKGROUND, tmcr_dyjetsTemplate)
    tmcr_dyjets.setParamEffect(lumi, nlumi)
    tmcr_dyjets.setParamEffect(trig_met, ntrig_met)
    tmcr_dyjets.setParamEffect(veto_tau, nveto_tau)
    tmcr_dyjets.setParamEffect(zjetsMC_norm, nVjets_norm)
    tmcr_dyjets.setParamEffect(jec, njec)
    tmcr_dyjets.setParamEffect(id_mu, nlepton)
    tmcr_dyjets.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(tmcr_dyjets, param, tmcr_central, tmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "DY+jets", "tmcr", tmcr_dyjets, category)
    addVJetsSyst(background, recoil, "DY+jets", "tmcr", tmcr_dyjets, category)
    tmcr.addSample(tmcr_dyjets)

    tmcr_vvTemplate = template(background, "VV", "nominal", recoil, "tmcr", category, read_sumw2=True)
    tmcr_vv = rl.TemplateSample(ch_name + "_vvMC", rl.Sample.BACKGROUND, tmcr_vvTemplate)
    tmcr_vv.setParamEffect(lumi, nlumi)
    tmcr_vv.setParamEffect(trig_met, ntrig_met)
    tmcr_vv.setParamEffect(veto_tau, nveto_tau)
    tmcr_vv.setParamEffect(vv_norm, nMinor_norm)
    tmcr_vv.setParamEffect(jec, njec)
    tmcr_vv.setParamEffect(id_mu, nlepton)
    tmcr_vv.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(tmcr_vv, param, tmcr_central, tmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "VV", "tmcr", tmcr_vv, category)
    tmcr.addSample(tmcr_vv)

    tmcr_hbbTemplate = template(background, "Hbb", "nominal", recoil, "tmcr", category, read_sumw2=True)
    tmcr_hbb = rl.TemplateSample(ch_name + "_hbbMC", rl.Sample.BACKGROUND, tmcr_hbbTemplate)
    tmcr_hbb.setParamEffect(lumi, nlumi)
    tmcr_hbb.setParamEffect(trig_met, ntrig_met)
    tmcr_hbb.setParamEffect(veto_tau, nveto_tau)
    tmcr_hbb.setParamEffect(hbb_norm, nMinor_norm)
    tmcr_hbb.setParamEffect(jec, njec)
    tmcr_hbb.setParamEffect(id_mu, nlepton)
    tmcr_hbb.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(tmcr_hbb, param, tmcr_central, tmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "Hbb", "tmcr", tmcr_hbb, category)
    tmcr.addSample(tmcr_hbb)

    tmcr_qcdTemplate = template(background, "QCD", "nominal", recoil, "tmcr", category, read_sumw2=True)
    tmcr_qcd = rl.TemplateSample(ch_name + "_qcdMC", rl.Sample.BACKGROUND, tmcr_qcdTemplate)
    tmcr_qcd.setParamEffect(lumi, nlumi)
    tmcr_qcd.setParamEffect(trig_met, ntrig_met)
    tmcr_qcd.setParamEffect(veto_tau, nveto_tau)
    tmcr_qcd.setParamEffect(qcdmu_norm, nqcd_norm)
    tmcr_qcd.setParamEffect(jec, njec)
    tmcr_qcd.setParamEffect(id_mu, nlepton)
    tmcr_qcd.setParamEffect(iso_mu, nlepton)
    addBBliteSyst(tmcr_qcd, param, tmcr_central, tmcr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "QCD", "tmcr", tmcr_qcd, category)
    tmcr.addSample(tmcr_qcd)

    ###
    # End of single muon top control region
    ###

    ###
    ###
    # Single electron top control region
    ###
    ###

    ch_name = "tecr" + model_id
    tecr = rl.Channel(ch_name)
    model.addChannel(tecr)

    ###
    # Add data distribution to the channel
    ###

    if year == "2018":
        dataTemplate = template(data, "EGamma", "data", recoil, "tecr", category)
    else:
        dataTemplate = template(data, "SingleElectron", "data", recoil, "tecr", category)
    tecr.setObservation(dataTemplate)

    ###
    # top-antitop data-driven model
    ###

    if not isttMC:
        tecr_ttTemplate = template(background, "TT", "nominal", recoil, "tecr", category, min_value=1., read_sumw2=True)
        tecr_ttMC = rl.TemplateSample("tecr" + model_id + "_ttMC", rl.Sample.BACKGROUND, tecr_ttTemplate)
        tecr_ttMC.setParamEffect(lumi, nlumi)
        tecr_ttMC.setParamEffect(trig_e, ntrig_e)
        tecr_ttMC.setParamEffect(veto_tau, nveto_tau)
        tecr_ttMC.setParamEffect(ttMC_norm, nMinor_norm)
        tecr_ttMC.setParamEffect(jec, njec)
        tecr_ttMC.setParamEffect(id_e, nlepton)
        tecr_ttMC.setParamEffect(reco_e, nlepton)
        tecr_ttMC.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoil, "TT", "tecr", tecr_ttMC, category)

        #### Transfer Factor
        tecr_ttTransferFactor = tecr_ttMC.getExpectation() / sr_ttMC.getExpectation()
        tecr_tt = rl.TransferFactorSample(ch_name + "_tt", rl.Sample.BACKGROUND, tecr_ttTransferFactor, sr_tt)
        tecr.addSample(tecr_tt)

    ###
    # Other MC-driven processes
    ###

    nbins = len(dataTemplate[1]) - 1
    param = [None for _ in range(nbins)]
    for i in range(nbins):
        param[i] = rl.NuisanceParameter(ch_name + '_mcstat_bin%i' % i, combinePrior='shape')
    
    MCbkgList = ["ST", "DY+jets", "VV", "Hbb", "W+jets", "QCD"]
    if isttMC: MCbkgList.append("TT")
    tecr_central, tecr_error2 = get_mergedMC_stat_variations(background, recoil, "tecr", category, MCbkgList)
    
    if isttMC:
        tecr_ttTemplate = template(background, "TT", "nominal", recoil, "tecr", category, min_value=1., read_sumw2=True)
        tecr_tt = rl.TemplateSample("tecr" + model_id + "_ttMC", rl.Sample.BACKGROUND, tecr_ttTemplate)
        tecr_tt.setParamEffect(lumi, nlumi)
        tecr_tt.setParamEffect(trig_e, ntrig_e)
        tecr_tt.setParamEffect(veto_tau, nveto_tau)
        tecr_tt.setParamEffect(ttMC_norm, nMinor_norm)
        tecr_tt.setParamEffect(jec, njec)
        tecr_tt.setParamEffect(id_e, nlepton)
        tecr_tt.setParamEffect(reco_e, nlepton)
        addBBliteSyst(tecr_tt, param, tecr_central, tecr_error2, epsilon=1e-5)
        addBtagSyst(background, recoil, "TT", "tecr", tecr_tt, category)
        tecr.addSample(tecr_tt)

    tecr_wjetsTemplate = template(background, "W+jets", "nominal", recoil, "tecr", category, read_sumw2=True)
    tecr_wjets = rl.TemplateSample(ch_name + "_wjetsMC", rl.Sample.BACKGROUND, tecr_wjetsTemplate)
    tecr_wjets.setParamEffect(lumi, nlumi)
    tecr_wjets.setParamEffect(trig_e, ntrig_e)
    tecr_wjets.setParamEffect(veto_tau, nveto_tau)
    tecr_wjets.setParamEffect(wjetsMC_norm, nVjets_norm)
    tecr_wjets.setParamEffect(jec, njec)
    tecr_wjets.setParamEffect(id_e, nlepton)
    tecr_wjets.setParamEffect(reco_e, nlepton)
    addBBliteSyst(tecr_wjets, param, tecr_central, tecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "W+jets", "tecr", tecr_wjets, category)
    addVJetsSyst(background, recoil, "W+jets", "tecr", tecr_wjets, category)
    tecr.addSample(tecr_wjets)

    tecr_stTemplate = template(background, "ST", "nominal", recoil, "tecr", category, read_sumw2=True)
    tecr_st = rl.TemplateSample(ch_name + "_stMC", rl.Sample.BACKGROUND, tecr_stTemplate)
    tecr_st.setParamEffect(lumi, nlumi)
    tecr_st.setParamEffect(trig_e, ntrig_e)
    tecr_st.setParamEffect(veto_tau, nveto_tau)
    tecr_st.setParamEffect(st_norm, nMinor_norm)
    tecr_st.setParamEffect(jec, njec)
    tecr_st.setParamEffect(id_e, nlepton)
    tecr_st.setParamEffect(reco_e, nlepton)
    addBBliteSyst(tecr_st, param, tecr_central, tecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "ST", "tecr", tecr_st, category)
    tecr.addSample(tecr_st)

    tecr_dyjetsTemplate = template(background, "DY+jets", "nominal", recoil, "tecr", category, read_sumw2=True)
    tecr_dyjets = rl.TemplateSample(ch_name + "_dyjetsMC", rl.Sample.BACKGROUND, tecr_dyjetsTemplate)
    tecr_dyjets.setParamEffect(lumi, nlumi)
    tecr_dyjets.setParamEffect(trig_e, ntrig_e)
    tecr_dyjets.setParamEffect(veto_tau, nveto_tau)
    tecr_dyjets.setParamEffect(zjetsMC_norm, nVjets_norm)
    tecr_dyjets.setParamEffect(jec, njec)
    tecr_dyjets.setParamEffect(id_e, nlepton)
    tecr_dyjets.setParamEffect(reco_e, nlepton)
    addBBliteSyst(tecr_dyjets, param, tecr_central, tecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "DY+jets", "tecr", tecr_dyjets, category)
    addVJetsSyst(background, recoil, "DY+jets", "tecr", tecr_dyjets, category)
    tecr.addSample(tecr_dyjets)

    tecr_vvTemplate = template(background, "VV", "nominal", recoil, "tecr", category, read_sumw2=True)
    tecr_vv = rl.TemplateSample(ch_name + "_vvMC", rl.Sample.BACKGROUND, tecr_vvTemplate)
    tecr_vv.setParamEffect(lumi, nlumi)
    tecr_vv.setParamEffect(trig_e, ntrig_e)
    tecr_vv.setParamEffect(veto_tau, nveto_tau)
    tecr_vv.setParamEffect(vv_norm, nMinor_norm)
    tecr_vv.setParamEffect(jec, njec)
    tecr_vv.setParamEffect(id_e, nlepton)
    tecr_vv.setParamEffect(reco_e, nlepton)
    addBBliteSyst(tecr_vv, param, tecr_central, tecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "VV", "tecr", tecr_vv, category)
    tecr.addSample(tecr_vv)

    tecr_hbbTemplate = template(background, "Hbb", "nominal", recoil, "tecr", category, read_sumw2=True)
    tecr_hbb = rl.TemplateSample(ch_name + "_hbbMC", rl.Sample.BACKGROUND, tecr_hbbTemplate)
    tecr_hbb.setParamEffect(lumi, nlumi)
    tecr_hbb.setParamEffect(trig_e, ntrig_e)
    tecr_hbb.setParamEffect(veto_tau, nveto_tau)
    tecr_hbb.setParamEffect(hbb_norm, nMinor_norm)
    tecr_hbb.setParamEffect(jec, njec)
    tecr_hbb.setParamEffect(id_e, nlepton)
    tecr_hbb.setParamEffect(reco_e, nlepton)
    addBBliteSyst(tecr_hbb, param, tecr_central, tecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "Hbb", "tecr", tecr_hbb, category)
    tecr.addSample(tecr_hbb)

    tecr_qcdTemplate = template(background, "QCD", "nominal", recoil, "tecr", category, read_sumw2=True)
    tecr_qcd = rl.TemplateSample(ch_name + "_qcdMC", rl.Sample.BACKGROUND, tecr_qcdTemplate)
    tecr_qcd.setParamEffect(lumi, nlumi)
    tecr_qcd.setParamEffect(trig_e, ntrig_e)
    tecr_qcd.setParamEffect(veto_tau, nveto_tau)
    tecr_qcd.setParamEffect(qcde_norm, nqcd_norm)
    tecr_qcd.setParamEffect(jec, njec)
    tecr_qcd.setParamEffect(id_e, nlepton)
    tecr_qcd.setParamEffect(reco_e, nlepton)
    addBBliteSyst(tecr_qcd, param, tecr_central, tecr_error2, epsilon=1e-5) ### replace autoMCStats
    addBtagSyst(background, recoilbin, "QCD", "tecr", tecr_qcd, category)
    tecr.addSample(tecr_qcd)

    ###
    # End of single electron top control region
    ###

    return model


if __name__ == "__main__":
    if not os.path.exists("datacards"):
        os.mkdir("datacards")
    parser = OptionParser()
    parser.add_option("-y", "--year", help="year", dest="year", default="2018")
    parser.add_option("-m", "--mass", help="mass", dest="mass", default="40to300")
    parser.add_option("-f", "--fakedata", help="replace data to sum of backgrounds", action="store_true", dest="fakedata")
    (options, args) = parser.parse_args()
    year = options.year
    mass = options.mass

    #####
    ###
    # Preparing Rhalphabeth
    ###
    #####

    ###
    # Extract histograms from input file and remap
    ###

    hists = load("hists/darkhiggs" + year + ".scaled")
    hists = remap_histograms(hists)

    ###
    # Preparing histograms for Rhalphabeth
    ###

    background = {}
    for r in hists["bkg"]["template"].identifiers("region"):
        background[str(r)] = hists["bkg"]["template"].integrate("region", r)
    
    ###
    # Establishing 2D binning
    ###
    
    recoilbins = np.array(recoil_binning)
    nrecoil = len(recoilbins) - 1
    msdbins = np.array(mass_binning)
    msd = rl.Observable('fjmass', msdbins)
    # here we derive these all at once with 2D array
    ptpts, msdpts = np.meshgrid(recoilbins[:-1] + 0.3 * np.diff(recoilbins), msdbins[:-1] + 0.5 * np.diff(msdbins), indexing='ij')
    recoilscaled = (ptpts - recoil_binning[0]) / (recoil_binning[-1] - recoil_binning[0])
    msdscaled = (msdpts - mass_binning[0]) / (mass_binning[-1] - mass_binning[0])

    ###
    # Calculating average pass-to-fail ration
    ###
    
    def efficiency(pass_templ, fail_templ, qcdmodel):
        qcdpass, qcdfail = 0., 0.
        for recoilbin in range(nrecoil):
            failCh = rl.Channel("recoilbin%d%s" % (recoilbin, 'fail'))
            passCh = rl.Channel("recoilbin%d%s" % (recoilbin, 'pass'))
            qcdmodel.addChannel(failCh)
            qcdmodel.addChannel(passCh)
            failCh.setObservation(fail_templ[recoilbin])
            passCh.setObservation(pass_templ[recoilbin])
            qcdfail += failCh.getObservation().sum()
            qcdpass += passCh.getObservation().sum()

        return qcdpass / qcdfail

    ###
    # Creating first Bernstein polynomial that represents the MC pass-to-fail ratio
    # Incorporates the dependence on mass/recoil (residual tagger correlation, HF fraction)
    # Includes statistical uncertainty by fitting the by-by-bin MC pass-to-fail ratio
    ###

    zjetspass_templ = []
    zjetsfail_templ = []
    for recoilbin in range(nrecoil):
        zjetspass_templ.append(template(background, "Z+jets", "nominal", recoilbin, "sr", "pass"))
        zjetsfail_templ.append(template(background, "Z+jets", "nominal", recoilbin, "sr", "fail"))

    zjetsmodel = rl.Model("zjetsmodel")
    zjetseff = efficiency(zjetspass_templ, zjetsfail_templ, zjetsmodel)
    tf_MCtemplZ = rl.BernsteinPoly("tf_MCtemplZ", (0, 1), ['recoil', 'fjmass'], limits=(1e-5, 10))
    tf_MCtemplZ_params = zjetseff * tf_MCtemplZ(recoilscaled, msdscaled)

    wjetspass_templ = []
    wjetsfail_templ = []
    for recoilbin in range(nrecoil):
        wjetspass_templ.append(template(background, "W+jets", "nominal", recoilbin, "sr", "pass"))
        wjetsfail_templ.append(template(background, "W+jets", "nominal", recoilbin, "sr", "fail"))

    wjetsmodel = rl.Model("wjetsmodel")
    wjetseff = efficiency(wjetspass_templ, wjetsfail_templ, wjetsmodel)
    tf_MCtemplW = rl.BernsteinPoly("tf_MCtemplW", (0, 1), ['recoil', 'fjmass'], limits=(1e-5, 10))
    tf_MCtemplW_params = wjetseff * tf_MCtemplW(recoilscaled, msdscaled)
    
    ###
    # Prepare model for the MC ratio fit
    ##

    def rhalphabeth(pass_templ, fail_templ, qcdmodel, tf_MCtempl_params):

        for recoilbin in range(nrecoil):
            failCh = qcdmodel['recoilbin%dfail' % recoilbin]
            passCh = qcdmodel['recoilbin%dpass' % recoilbin]
            failObs = failCh.getObservation()
            qcdparams = np.array([rl.IndependentParameter('qcdparam_ptbin%d_msdbin%d' % (recoilbin, i), 0) for i in range(msd.nbins)])
            sigmascale = 10.
            scaledparams = failObs * (1 + sigmascale/np.maximum(1., np.sqrt(failObs)))**qcdparams
            fail_qcd = rl.ParametericSample('recoilbin'+str(recoilbin)+'fail_'+qcdmodel.name, rl.Sample.BACKGROUND, msd, scaledparams)
            failCh.addSample(fail_qcd)
            pass_qcd = rl.TransferFactorSample('recoilbin'+str(recoilbin)+'pass_'+qcdmodel.name, rl.Sample.BACKGROUND, tf_MCtempl_params[recoilbin, :], fail_qcd)
            passCh.addSample(pass_qcd)

        return qcdmodel

    zjetsmodel = rhalphabeth(zjetspass_templ, zjetsfail_templ, zjetsmodel, tf_MCtemplZ_params)
    wjetsmodel = rhalphabeth(wjetspass_templ, wjetsfail_templ, wjetsmodel, tf_MCtemplW_params)
    
    ###
    # Perform the fit to the bin-by-bin MC ratio
    ###

    def fit(model):
        qcdfit_ws = ROOT.RooWorkspace('qcdfit_ws')
        simpdf, obs = model.renderRoofit(qcdfit_ws)
        qcdfit = simpdf.fitTo(obs,
                            ROOT.RooFit.Extended(True),
                            ROOT.RooFit.SumW2Error(True),
                            ROOT.RooFit.Strategy(2),
                            ROOT.RooFit.Save(),
                            ROOT.RooFit.Minimizer('Minuit2', 'migrad'),
                            ROOT.RooFit.PrintLevel(-1),
                            )
        qcdfit_ws.add(qcdfit)
        #if "pytest" not in sys.modules:
        #    qcdfit_ws.writeToFile(os.path.join(str(tmpdir), 'testModel_qcdfit.root'))
        if qcdfit.status() != 0:
            raise RuntimeError('Could not fit qcd')

        return qcdfit

    zjetsfit = fit(zjetsmodel)
    wjetsfit = fit(wjetsmodel)

    ###
    # Use the post-fit values of the Bernstein polynomial coefficients
    ###
    
    def shape(fit, tf_MCtempl):
        param_names = [p.name for p in tf_MCtempl.parameters.reshape(-1)]
        decoVector = rl.DecorrelatedNuisanceVector.fromRooFitResult(tf_MCtempl.name + '_deco', fit, param_names)
        tf_MCtempl.parameters = decoVector.correlated_params.reshape(tf_MCtempl.parameters.shape)
        tf_MCtempl_params_final = tf_MCtempl(recoilscaled, msdscaled)

        return tf_MCtempl_params_final

    tf_MCtemplW_params_final = shape(wjetsfit, tf_MCtemplW)
    tf_MCtemplZ_params_final = shape(zjetsfit, tf_MCtemplZ)
    
    ###
    # Create Bernstein polynomials that represent the correction to the MC ratio
    ###
    
    tf_dataResidualW = rl.BernsteinPoly("tf_dataResidualW"+year, (0, 1), ['recoil', 'fjmass'], limits=(1e-5, 10))
    tf_dataResidualW_params = tf_dataResidualW(recoilscaled, msdscaled)
    tf_dataResidualZ = rl.BernsteinPoly("tf_dataResidualZ"+year, (0, 1), ['recoil', 'fjmass'], limits=(1e-5, 10))
    tf_dataResidualZ_params = tf_dataResidualZ(recoilscaled, msdscaled)

    #####
    ###
    # End of Rhalphabeth preparation
    ###
    #####
    
    ###
    ###
    # Set up other systematics
    ###
    ###
    
    lumi = rl.NuisanceParameter("lumi" + year, "lnN")
    zjets_norm = rl.NuisanceParameter("zjets_norm", "lnN")
    wjets_norm = rl.NuisanceParameter("wjets_norm", "lnN")
    id_e = rl.NuisanceParameter("id_e" + year, "lnN")
    id_mu = rl.NuisanceParameter("id_mu" + year, "lnN")
    id_pho = rl.NuisanceParameter("id_pho" + year, "lnN")
    reco_e = rl.NuisanceParameter("reco_e" + year, "lnN")
    iso_mu = rl.NuisanceParameter("iso_mu" + year, "lnN")
    trig_e = rl.NuisanceParameter("trig_e" + year, "lnN")
    trig_met = rl.NuisanceParameter("trig_met" + year, "lnN")
    trig_pho = rl.NuisanceParameter("trig_pho" + year, "lnN")
    veto_tau = rl.NuisanceParameter("veto_tau" + year, "lnN")
    jec = rl.NuisanceParameter("jec" + year, "lnN")
    btag = rl.NuisanceParameter("btag" + year, "shape")  # AK4 btag
    ew1 = rl.NuisanceParameter("ew1", "lnN")
    #ew2G = rl.NuisanceParameter("ew2G", "lnN")
    ew2W = rl.NuisanceParameter("ew2W", "lnN")
    ew2Z = rl.NuisanceParameter("ew2Z", "lnN")
    #ew3G = rl.NuisanceParameter("ew3G", "lnN")
    ew3W = rl.NuisanceParameter("ew3W", "lnN")
    ew3Z = rl.NuisanceParameter("ew3Z", "lnN")
    mix = rl.NuisanceParameter("mix", "lnN")
    #muF = rl.NuisanceParameter("muF", "lnN")
    #muR = rl.NuisanceParameter("muR", "lnN")
    qcd1 = rl.NuisanceParameter("qcd1", "lnN")
    qcd2 = rl.NuisanceParameter("qcd2", "lnN")
    qcd3 = rl.NuisanceParameter("qcd3", "lnN")
    whf_fraction = rl.NuisanceParameter("whf_fraction", "lnN")
    zhf_fraction = rl.NuisanceParameter("zhf_fraction", "lnN")
    
    ###
    # Set lnN or shape numbers
    ###

    nlumi = 1.027
    ntrig_met = 1.02
    ntrig_e = 1.01
    nveto_tau = 1.03
    njec = 1.05
    nlepton = 1.02 ## id_mu, iso_mu, id_e, reco_e
    nVjets_norm = 1.4 ## wjetsMC_norm, wjets_norm, zjetsMC_norm, zjets_norm, whf_fraction, zhf_fraction
    nMinor_norm = 1.2 ## tt_norm, ttMC_norm, st_norm, vv_norm, hbb_norm
    nqcd_norm = 2.0 ## qcdsig_norm, qcde_norm, qcdmu_norm

    ###
    ###
    # End of systematics setup
    ###
    ###
    
    ###
    ###
    # Prepare histograms for the fit
    ###
    ###
    
    ###
    # Split mass range
    ###
    
    
    if '40to' in mass:
        cut = mass.split('40to')[1]
        index = mass_binning.index(int(cut))
        mass_binning = mass_binning[:(index+1)]
        nmass = len(mass_binning) - 1
        tf_MCtemplZ_params_final = tf_MCtemplZ_params_final[:, :nmass]
        tf_dataResidualZ_params = tf_dataResidualZ_params[:, :nmass]
        tf_MCtemplW_params_final = tf_MCtemplW_params_final[:, :nmass]
        tf_dataResidualW_params = tf_dataResidualW_params[:, :nmass]
    if 'to300' in mass:
        nmass = len(mass_binning) - 1
        cut = mass.split('to300')[0]
        index = mass_binning.index(int(cut))
        mass_binning = mass_binning[index:]
        nmass = nmass - (len(mass_binning) - 1)
        tf_MCtemplZ_params_final = tf_MCtemplZ_params_final[:, nmass:]
        tf_dataResidualZ_params = tf_dataResidualZ_params[:, nmass:]
        tf_MCtemplW_params_final = tf_MCtemplW_params_final[:, nmass:]
        tf_dataResidualW_params = tf_dataResidualW_params[:, nmass:]
        
    ###
    # Reload and remap histograms 
    ###

    hists = load("hists/darkhiggs" + year + ".scaled")
    hists = remap_histograms(hists)

    ###
    # Manipulate histograms to be fed to the model
    ###

    signal_hists = hists["sig"]
    signal = {}
    for r in signal_hists["template"].identifiers("region"):
        signal[str(r)] = signal_hists["template"].integrate("region", r)
        
    bkg_hists = hists["bkg"]
    background = {}
    for r in bkg_hists["template"].identifiers("region"):
        background[str(r)] = bkg_hists["template"].integrate("region", r)

    data_hists = hists["data"]
    data = {}
    for r in data_hists["template"].identifiers("region"):
        data[str(r)] = data_hists["template"].integrate("region", r)

    model_dict = {}
    for recoilbin in range(nrecoil):

        sr_zjetsMCFailTemplate = template(background, "Z+jets", "nominal", recoilbin, "sr", "fail", read_sumw2=True)
        sr_zjetsMCFail = rl.TemplateSample(
            "sr" + year + "fail" + "mass" + mass + "recoil" + str(recoilbin) + "_zjetsMC",
            rl.Sample.BACKGROUND,
            sr_zjetsMCFailTemplate
        )
        sr_zjetsMCFail.setParamEffect(lumi, nlumi)
        sr_zjetsMCFail.setParamEffect(zjets_norm, nVjets_norm)
        sr_zjetsMCFail.setParamEffect(trig_met, ntrig_met)
        sr_zjetsMCFail.setParamEffect(veto_tau, nveto_tau)
        sr_zjetsMCFail.setParamEffect(jec, njec)
        sr_zjetsMCFail.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoilbin, "Z+jets", "sr", sr_zjetsMCFail, "fail")
        addVJetsSyst(background, recoilbin, "Z+jets", "sr", sr_zjetsMCFail, "fail")

        sr_zjetsObservable = rl.Observable("fjmass", sr_zjetsMCFailTemplate[1])
        sr_zjetsBinYields = np.array([rl.IndependentParameter('tmp', b, 1e-5, sr_zjetsMCFailTemplate[0].max()*2) for b in sr_zjetsMCFailTemplate[0]])

        sr_zjetsFail = rl.ParametericSample(
            "sr" + year + "fail" + "mass" + mass + "recoil" + str(recoilbin) + "_zjets",
            rl.Sample.BACKGROUND,
            sr_zjetsObservable,
            sr_zjetsBinYields
        )

        sr_wjetsMCFailTemplate = template(background, "W+jets", "nominal", recoilbin, "sr", "fail", read_sumw2=True)
        sr_wjetsMCFail = rl.TemplateSample(
            "sr" + year + "fail" + "mass" + mass + "recoil" + str(recoilbin) + "_wjetsMC",
            rl.Sample.BACKGROUND,
            sr_wjetsMCFailTemplate
        )
        sr_wjetsMCFail.setParamEffect(lumi, nlumi)
        sr_wjetsMCFail.setParamEffect(wjets_norm, nVjets_norm)
        sr_wjetsMCFail.setParamEffect(trig_met, ntrig_met)
        sr_wjetsMCFail.setParamEffect(veto_tau, nveto_tau)
        sr_wjetsMCFail.setParamEffect(jec, njec)
        sr_wjetsMCFail.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoilbin, "W+jets", "sr", sr_wjetsMCFail, "fail")
        addVJetsSyst(background, recoilbin, "W+jets", "sr", sr_wjetsMCFail, "fail")

        sr_wjetsFailTransferFactor = sr_wjetsMCFail.getExpectation() / sr_zjetsMCFail.getExpectation()
        sr_wjetsFail = rl.TransferFactorSample(
            "sr" + year + "fail" + "mass" + mass + "recoil" + str(recoilbin) + "_wjets",
            rl.Sample.BACKGROUND,
            sr_wjetsFailTransferFactor,
            sr_zjetsFail
        )

        sr_zjetsMCPassTemplate = template(background, "Z+jets", "nominal", recoilbin, "sr", "pass", read_sumw2=True)
        sr_zjetsMCPass = rl.TemplateSample(
            "sr" + year + "pass" + "mass" + mass + "recoil" + str(recoilbin) + "_zjetsMC",
            rl.Sample.BACKGROUND,
            sr_zjetsMCPassTemplate
        )
        sr_zjetsMCPass.setParamEffect(lumi, nlumi)
        sr_zjetsMCPass.setParamEffect(zjets_norm, nVjets_norm)
        sr_zjetsMCPass.setParamEffect(trig_met, ntrig_met)
        sr_zjetsMCPass.setParamEffect(veto_tau, nveto_tau)
        sr_zjetsMCPass.setParamEffect(jec, njec)
        sr_zjetsMCPass.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoilbin, "Z+jets", "sr", sr_zjetsMCPass, "pass")
        addVJetsSyst(background, recoilbin, "Z+jets", "sr", sr_zjetsMCPass, "pass")

        #tf_paramsZdeco = sr_zjetsMCPassTemplate[0] / sr_zjetsMCFailTemplate[0]
        tf_paramsZ = zjetseff *tf_MCtemplZ_params_final[recoilbin, :] * tf_dataResidualZ_params[recoilbin, :]

        sr_zjetsPass = rl.TransferFactorSample(
            "sr" + year + "pass" + "mass" + mass + "recoil" + str(recoilbin) + "_zjets",
            rl.Sample.BACKGROUND,
            tf_paramsZ,
            sr_zjetsFail
        )

        sr_wjetsMCPassTemplate = template(background, "W+jets", "nominal", recoilbin, "sr", "pass", read_sumw2=True)
        sr_wjetsMCPass = rl.TemplateSample(
            "sr" + year + "pass" + "mass" + mass + "recoil" + str(recoilbin) + "_wjetsMC",
            rl.Sample.BACKGROUND,
            sr_wjetsMCPassTemplate
        )
        sr_wjetsMCPass.setParamEffect(lumi, nlumi)
        sr_wjetsMCPass.setParamEffect(wjets_norm, nVjets_norm)
        sr_wjetsMCPass.setParamEffect(trig_met, ntrig_met)
        sr_wjetsMCPass.setParamEffect(veto_tau, nveto_tau)
        sr_wjetsMCPass.setParamEffect(jec, njec)
        sr_wjetsMCPass.autoMCStats(epsilon=1e-5) ### autoMCStats is used for TransferFactorSample
        addBtagSyst(background, recoilbin, "W+jets", "sr", sr_wjetsMCPass, "pass")
        addVJetsSyst(background, recoilbin, "W+jets", "sr", sr_wjetsMCPass, "pass")

        #tf_paramsWdeco = sr_wjetsMCPassTemplate[0] / sr_wjetsMCFailTemplate[0]
        tf_paramsW = wjetseff *tf_MCtemplW_params_final[recoilbin, :] * tf_dataResidualW_params[recoilbin, :]

        sr_wjetsPass = rl.TransferFactorSample(
            "sr" + year + "pass" + "mass" + mass + "recoil" + str(recoilbin) + "_wjets",
            rl.Sample.BACKGROUND,
            tf_paramsW,
            sr_wjetsFail
        )

        for category in ["pass", "fail"]:
            
            qcdpho_norm = rl.NuisanceParameter("qcdpho_norm" + year + category, "lnN")
            qcde_norm = rl.NuisanceParameter("qcde_norm" + year + category, "lnN")
            qcdmu_norm = rl.NuisanceParameter("qcdmu_norm" + year + category, "lnN")
            qcdsig_norm = rl.NuisanceParameter("qcdsig_norm" + year + category, "lnN")
            st_norm = rl.NuisanceParameter("st_norm" + year + category, "lnN")
            ttMC_norm = rl.NuisanceParameter("tt_norm" + year + category, "lnN")
            vv_norm = rl.NuisanceParameter("vv_norm" + year + category, "lnN")
            hbb_norm = rl.NuisanceParameter("hbb_norm" + year + category, "lnN")
            wjetsMC_norm = rl.NuisanceParameter("wjets_norm" + year + category, "lnN")
            zjetsMC_norm = rl.NuisanceParameter("zjets_norm" + year + category, "lnN")
            
            isttMC = ('40to' in mass and not 'to300' in mass) | (category=='fail') | (recoilbin==4)
            iswjetsMC = (recoilbin==4) & (category=='pass')

            with open(
                    "data/models/"
                    + "darkhiggs"
                    + "-"
                    + year
                    + "-"
                    + category
                    + "-mass"
                    + mass
                    + "-recoil"
                    + str(recoilbin)
                    + ".model",
                    "wb",
            ) as fout:
                pickle.dump(model(year, mass, recoilbin, category), fout, protocol=2)
