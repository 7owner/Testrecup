'use strict';

// Controle de coherence microcode / proprietes / tableau d'adresses avec les
// regles du systeme TIL (MS_Cube_Microcode_et_Programmation.pdf FR 1.157 et
// modeles « MODEL Microcode » de TIL). Renvoie une liste de constats.

const REG = {
  X: /^X([ABC])(\d{2})(\d{2})$/,
  D: /^D([ABC])(\d{2})(\d{2})$/,
  L: /^L([ABC])(\d+)$/,
  TN: /^TN(\d+)$/,
  MRV: /^([MRV])(\d+)$/,
};
const EVENEMENTS_LECTEUR = ['AUTORISE', 'INTERDIT', 'ATT_ESCORTE', 'VISIT_AUTORISE', 'ESCORTE_KO', 'CR_OK', 'CR_KO', 'CR_TIMEOUT'];

// Plages du systeme : modules 01-16 et voies 01-16, lecteurs 1-8 par bus,
// 32 timers, registres virtuels ToR 1-128.
function registreValide(reg) {
  let m;
  if ((m = reg.match(REG.X)) || (m = reg.match(REG.D))) {
    const adresse = Number(m[2]);
    const voie = Number(m[3]);
    return adresse >= 1 && adresse <= 16 && voie >= 1 && voie <= 16;
  }
  if ((m = reg.match(REG.L))) return Number(m[2]) >= 1 && Number(m[2]) <= 8;
  if ((m = reg.match(REG.TN))) return Number(m[1]) >= 1 && Number(m[1]) <= 32;
  if ((m = reg.match(REG.MRV))) return Number(m[2]) >= 1 && Number(m[2]) <= 128;
  return false;
}

function controlerSyntaxe(code, note) {
  const lignes = code.split('\n').map(l => l.replace(/;.*$/, '').trim()).filter(Boolean);
  let niveauSi = 0;
  let pulses = 0;
  const timersArmes = new Set();
  const timersEv = new Set();
  lignes.forEach(l => {
    let m;
    if ((m = l.match(/^SET_RDR_COLOR\((\d+),[a-z]+,[a-z]+,[a-z]+,[a-z]+\)$/))) {
      if (Number(m[1]) < 1 || Number(m[1]) > 24) note('ERREUR', `SET_RDR_COLOR hors 1..24 : ${l}`);
      return;
    }
    if ((m = l.match(/^(PESCORT|PCLV)(\d+)=[\d,]+$/))) {
      if (Number(m[2]) < 1 || Number(m[2]) > 24) note('ERREUR', `${m[1]} hors 1..24 : ${l}`);
      return;
    }
    if ((m = l.match(/^EV\((\w+)(?:==(\w+))?\)$/))) {
      if (!registreValide(m[1])) note('ERREUR', `registre d'evenement invalide : ${l}`);
      if (m[1].startsWith('TN')) timersEv.add(m[1]);
      if (REG.L.test(m[1]) && !EVENEMENTS_LECTEUR.includes(m[2])) note('ERREUR', `evenement lecteur inconnu : ${l}`);
      return;
    }
    if ((m = l.match(/^SI\((\w+)==[01]\)$/))) {
      niveauSi += 1;
      if (!registreValide(m[1])) note('ERREUR', `registre de SI invalide : ${l}`);
      return;
    }
    if (l === 'FINSI') { niveauSi -= 1; return; }
    if ((m = l.match(/^(\w+)=(PULSE\((\d+)\)|\d+)$/))) {
      if (!registreValide(m[1])) note('ERREUR', `registre affecte invalide : ${l}`);
      if (m[1].startsWith('D')) note('ERREUR', `affectation d'une entree : ${l}`);
      if (m[3]) pulses += 1;
      if (m[1].startsWith('TN') && m[2] !== '0') timersArmes.add(m[1]);
      return;
    }
    note('ERREUR', `ligne non reconnue : ${l}`);
  });
  if (niveauSi !== 0) note('ERREUR', `SI / FINSI desequilibres (${niveauSi})`);
  timersArmes.forEach(tn => { if (!timersEv.has(tn)) note('ERREUR', `${tn} arme sans EV(${tn})`); });
  timersEv.forEach(tn => { if (!timersArmes.has(tn)) note('ERREUR', `EV(${tn}) sans armement`); });
  return { pulses, timers: timersArmes.size };
}

function controlerTillys(TIL, tillys, options) {
  const constats = [];
  const note = (gravite, message) => constats.push({ gravite, message });
  const code = TIL.genererMicrocodeTillys(tillys, options);
  const utl = TIL.genererUTLVersServeur(tillys, options);
  const srv = TIL.genererServeurVersUTL(tillys, options);
  const tableau = TIL.genererTableauAdresses(tillys);
  const bilan = controlerSyntaxe(code, note);

  const blocs = code.split(/\n;\/{64}\n;/).slice(1);
  const proprietaire = {};
  const prendre = (reg, qui) => {
    if (!reg) return;
    if (proprietaire[reg] && proprietaire[reg] !== qui) note('ERREUR', `${reg} partage entre ${proprietaire[reg]} et ${qui}`);
    proprietaire[reg] = qui;
  };
  const propriete = (texte, id, cle) => {
    const debut = `${id}.${cle}=`;
    const ligne = texte.split('\n').find(x => x.startsWith(debut));
    return ligne ? ligne.slice(debut.length).trim() : null;
  };

  tableau.filter(d => d.active && d.raccorde).forEach(d => {
    const p = tillys.portes[d.porteNum - 1];
    const id = d.triNum;
    const bloc = blocs.find(b => b.startsWith(`${id} `)) || '';
    if (!bloc) { note('ERREUR', `${id} : bloc absent du microcode`); return; }
    const regs = new Set(bloc.match(/\b(?:X[ABC]\d{4}|D[ABC]\d{4}|L[ABC]\d+|TN\d+|[MRV]\d+)\b/g) || []);
    const timerPotl = p.timerActif !== false && p.potlActif !== false;

    // Registres du microcode = registres du tableau d'adresses.
    const attendus = [d.lock, d.ledVert, d.ledRouge, d.lecteur];
    if (p.cmdHyperActif !== false) attendus.push(d.cmdHyper);
    if (timerPotl || p.effractionActive !== false) attendus.push(d.capteur);
    if (timerPotl) attendus.push(d.timer, d.regPotl, d.buzzer);
    if (p.effractionActive !== false) attendus.push(d.regEffrac);
    if (Number(p.bp) === 1) attendus.push(d.bp);
    if (d.lecteurSortie) attendus.push(d.lecteurSortie, d.ledVertSortie, d.ledRougeSortie);
    attendus.filter(Boolean).forEach(r => { if (!regs.has(r)) note('ERREUR', `${id} : ${r} du tableau absent du microcode`); });
    const permis = new Set([...attendus, d.buzzer, d.capteur].filter(Boolean));
    regs.forEach(r => { if (!permis.has(r)) note('ERREUR', `${id} : ${r} utilise mais absent du tableau`); });
    if (p.cmdHyperActif === false && regs.has(d.cmdHyper)) note('ERREUR', `${id} : commande hyperviseur desactivee mais ${d.cmdHyper} present`);
    if (!timerPotl && regs.has(d.timer)) note('ERREUR', `${id} : Timer / POTL desactive mais ${d.timer} present`);
    if (p.effractionActive === false && regs.has(d.regEffrac)) note('ERREUR', `${id} : effraction desactivee mais ${d.regEffrac} present`);

    // Registres virtuels = numero de la tete de lecture.
    [['cmdHyper', 'M'], ['timer', 'TN'], ['regEffrac', 'R'], ['regPotl', 'V']].forEach(([cle, prefixe]) => {
      if (d[cle] !== `${prefixe}${d.lecteurNum}`) note('ERREUR', `${id} : ${cle}=${d[cle]} au lieu de ${prefixe}${d.lecteurNum}`);
    });

    // Proprietes echangees avec le serveur.
    if (p.cmdHyperActif !== false && propriete(srv, id, 'cmd') !== d.cmdHyper) note('ERREUR', `${id} : .cmd incoherent`);
    if (propriete(utl, id, 'locked') !== d.capteur) note('ERREUR', `${id} : .locked incoherent`);
    if (p.effractionActive !== false && propriete(utl, id, 'forced') !== d.regEffrac) note('ERREUR', `${id} : .forced incoherent`);
    if (timerPotl && propriete(utl, id, 'potl') !== d.regPotl) note('ERREUR', `${id} : .potl incoherent`);
    if ((Number(p.dm) === 1) !== (propriete(utl, id, 'dm') === d.dm)) note('ERREUR', `${id} : .dm incoherent`);
    if ((Number(p.barreAntiPanique) === 1) !== (propriete(utl, id, 'ap') === d.ap)) note('ERREUR', `${id} : .ap incoherent`);

    // Lecteur clavier : modele TIL LC (PCLVx=3,4,10 et evenements CR_*).
    [[p.lecteurEntree, d.lecteur, d.lecteurNum], [p.lecteurSortie, d.lecteurSortie, d.lecteurNum + 1]].forEach(([type, lecteur, num]) => {
      if (String(type || '').toUpperCase() !== 'LCODE' || !lecteur) return;
      ['AUTORISE', 'CR_OK', 'CR_KO', 'CR_TIMEOUT', 'INTERDIT'].forEach(ev => {
        if (!bloc.includes(`EV(${lecteur}==${ev})`)) note('ECART', `${id} : lecteur clavier ${lecteur} sans EV(${lecteur}==${ev})`);
      });
      if (!new RegExp(`^PCLV${num}=3,4,10`, 'm').test(code)) note('ECART', `${id} : lecteur clavier ${lecteur} sans PCLV${num}=3,4,10`);
    });
    if (p.mode === 'visiteur' && !new RegExp(`^PESCORT${d.lecteurNum}=`, 'm').test(code)) note('ERREUR', `${id} : visiteur sans PESCORT${d.lecteurNum}`);

    // Aucun materiel ni registre partage entre deux portes.
    [d.lock, d.ledVert, d.ledRouge, d.buzzer, d.capteur, d.lecteur, d.cmdHyper, d.timer, d.regEffrac, d.regPotl,
      Number(p.bp) === 1 && d.bp, Number(p.dm) === 1 && d.dm, Number(p.barreAntiPanique) === 1 && d.ap,
      d.lecteurSortie, d.ledVertSortie, d.ledRougeSortie, d.buzzerSortie].filter(Boolean).forEach(r => prendre(r, id));
  });

  // Modules terrain : registres valides et sans chevauchement avec les portes.
  TIL.genererTableauModules(tillys).forEach(v => {
    if (!registreValide(v.registre)) note('ERREUR', `registre de module invalide ${v.registre}`);
    prendre(v.registre, `${v.moduleName} ${v.label}`);
  });

  // Une ligne SET_RDR_COLOR par MLP2 actif, sur le lecteur de son adresse de base.
  const couleurs = (code.match(/^SET_RDR_COLOR\((\d+)/gm) || []).map(s => Number(s.split('(')[1])).sort((a, b) => a - b);
  const attendues = (tillys.synopticModules || [])
    .filter(m => m.type === 'MLP2' && TIL.getModuleAddress(m) && (m.doorNums || []).some(n => tillys.portes[n - 1] && tillys.portes[n - 1].active))
    .map(m => TIL.BUS_OFFSETS[m.bus] + TIL.getModuleAddress(m))
    .sort((a, b) => a - b);
  if (couleurs.join() !== attendues.join()) note('ERREUR', `SET_RDR_COLOR ${couleurs.join(',')} au lieu de ${attendues.join(',')}`);

  return { constats, pulses: bilan.pulses, timers: bilan.timers, portes: tableau.filter(d => d.active && d.raccorde).length };
}

// Projet aleatoire valide : memes contraintes que l'application (MLP2 a 1 ou
// 2 tetes, porte a 2 lecteurs seule sur un MLP2 2L, adresses de l'allocateur).
function projetAleatoire(TIL, graine) {
  let s = graine;
  const r = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
  const choix = a => a[Math.floor(r() * a.length)];
  const t = TIL.creerTillys(0, `Alea ${graine}`);
  t.synopticModules = [];
  let num = 1;
  let n = 0;
  ['A', 'B', 'C'].forEach(bus => {
    const nombre = Math.floor(r() * 5);
    for (let k = 0; k < nombre && num <= 24; k += 1) {
      const slots = r() < 0.25 ? 1 : 2;
      const address = TIL.allocateAddress(t, bus, 'MLP2', { readerSlots: slots });
      if (!address) break;
      const module = { id: `M${(n += 1)}`, type: 'MLP2', bus, address, name: `MLP2 ${bus}${address}`, doorNums: [], readerSlots: slots };
      t.synopticModules.push(module);
      let tetes = slots;
      while (tetes > 0 && num <= 24) {
        const deux = tetes === 2 && module.doorNums.length === 0 && r() < 0.3;
        Object.assign(t.portes[num - 1], {
          active: r() < 0.9, batiment: choix(['A', 'B']), etage: choix(['N0', 'N1']), numeroPorte: String(100 + num),
          designation: `Porte ${num}`, lecteurEntree: choix(['LB', 'LB', 'LCode', 'LBio']), lecteurSortie: deux ? choix(['LB', 'LCode']) : '',
          bp: r() < 0.5 ? 1 : 0, dm: r() < 0.5 ? 1 : 0, barreAntiPanique: r() < 0.2 ? 1 : 0, mode: r() < 0.2 ? 'visiteur' : 'standard',
          cmdHyperActif: r() > 0.1, timerActif: r() > 0.15, potlActif: r() > 0.15, effractionActive: r() > 0.15, mlp2ModuleId: module.id,
        });
        module.doorNums.push(num);
        tetes -= deux ? 2 : 1;
        num += 1;
      }
    }
    if (r() < 0.5) { const a = TIL.allocateAddress(t, bus, 'MLIO'); if (a) t.synopticModules.push({ id: `IO${bus}`, type: 'MLIO', bus, address: a, name: `MLIO ${bus}${a}`, doorNums: [] }); }
    if (r() < 0.5) { const a = TIL.allocateAddress(t, bus, 'MLR8'); if (a) t.synopticModules.push({ id: `R8${bus}`, type: 'MLR8', bus, address: a, name: `MLR8 ${bus}${a}`, doorNums: [] }); }
  });
  if (num <= 24 && r() < 0.3) Object.assign(t.portes[num - 1], { active: true, numeroPorte: String(100 + num), designation: 'Orpheline', lecteurEntree: 'LB' });
  return t;
}

module.exports = { registreValide, controlerTillys, projetAleatoire };
