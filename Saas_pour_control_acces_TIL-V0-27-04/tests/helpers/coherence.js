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

// Tete de lecture 1..24 (SET_RDR_COLOR, PESCORT, PCLV, APERIO_OPEN / APERIO_CLOSE).
const teteValide = n => Number(n) >= 1 && Number(n) <= 24;

function controlerSyntaxe(code, note) {
  // Espaces internes ignores : APERIO_OPEN( 5 , 5 ) vaut APERIO_OPEN(5,5).
  const lignes = code.split('\n').map(l => l.replace(/;.*$/, '').replace(/\s+/g, '')).filter(Boolean);
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
    // Serrure APERIO pilotee par sa tete de lecture (firmware >= 4.2.0).
    if ((m = l.match(/^APERIO_OPEN\((\d+),(\d+)\)$/))) {
      if (!teteValide(m[1])) note('ERREUR', `APERIO_OPEN hors 1..24 : ${l}`);
      if (Number(m[2]) < 1) note('ERREUR', `APERIO_OPEN sans duree : ${l}`);
      return;
    }
    if ((m = l.match(/^APERIO_CLOSE\((\d+)\)$/))) {
      if (!teteValide(m[1])) note('ERREUR', `APERIO_CLOSE hors 1..24 : ${l}`);
      return;
    }
    // Lecteur biometrique : statut 00, 01 ou 02 sur un lecteur 1..8 du bus.
    if ((m = l.match(/^SI\(BIO_STATUS_([ABC])(\d+)==(\d+)\)$/))) {
      niveauSi += 1;
      if (Number(m[2]) < 1 || Number(m[2]) > 8) note('ERREUR', `BIO_STATUS hors lecteurs 1..8 : ${l}`);
      if (!/^0[0-2]$/.test(m[3])) note('ERREUR', `BIO_STATUS inconnu (00, 01 ou 02 attendu) : ${l}`);
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

// Porte APERIO : serrure APERIO ou lecteur APERIO (la serrure est la tete de lecture).
function estPorteAperio(p) {
  return [p.verrouillage, p.lecteurEntree].some(v => String(v || '').trim().toUpperCase() === 'APERIO');
}

// Instructions d'un bloc de porte, sans titre, commentaires ni espaces.
function instructionsBloc(bloc) {
  return bloc.split('\n').slice(1).map(l => l.replace(/;.*$/, '').replace(/\s+/g, '')).filter(Boolean);
}

// Instructions d'un evenement : de EV(...) exclu au prochain EV( exclu, ou null.
function instructionsEvenement(liste, ev) {
  const debut = liste.indexOf(ev);
  if (debut < 0) return null;
  const suite = liste.slice(debut + 1);
  const fin = suite.findIndex(l => l.startsWith('EV('));
  return fin === -1 ? suite : suite.slice(0, fin);
}

// Serrure APERIO = tete de lecture de la porte (MS_Cube, exemples 3.1 / 3.2) :
// X{bus}{lecteurLocal}03 ouvre, ...04 refuse, APERIO_OPEN(tete, s) pour BP et
// hyperviseur, aucun relais ni buzzer du MLP2.
function controlerPorteAperio(p, d, id, liste, regs, options, note) {
  const yy = String(d.lecteurLocal).padStart(2, '0');
  const ouverture = `X${d.bus}${yy}03`;
  const refus = `X${d.bus}${yy}04`;
  if (d.aperio !== true) note('ERREUR', `${id} : porte APERIO sans drapeau aperio dans le tableau d'adresses`);
  if (d.lock) note('ERREUR', `${id} : porte APERIO avec un relais ${d.lock}`);
  if (d.buzzer) note('ERREUR', `${id} : porte APERIO avec un buzzer ${d.buzzer}`);
  if (d.ledVert !== ouverture) note('ERREUR', `${id} : ouverture APERIO ${d.ledVert} au lieu de ${ouverture}`);
  if (d.ledRouge !== refus) note('ERREUR', `${id} : refus APERIO ${d.ledRouge} au lieu de ${refus}`);
  regs.forEach(r => {
    const m = r.match(/^X[ABC]\d{2}(\d{2})$/);
    if (m && (m[1] === '01' || m[1] === '02')) note('ERREUR', `${id} : registre relais ${r} sur une porte APERIO`);
  });

  const pulse = p.dureePulse || (options && options.pulse) || 50;
  liste.forEach(l => {
    let m;
    if ((m = l.match(/^APERIO_OPEN\((\d+),(\d+)\)$/))) {
      if (Number(m[1]) !== d.lecteurNum) note('ERREUR', `${id} : ${l} au lieu de la tete ${d.lecteurNum}`);
      if (pulse % 10 === 0 && Number(m[2]) !== pulse / 10) note('ERREUR', `${id} : ${l} au lieu de ${pulse / 10} s`);
    }
    if ((m = l.match(/^(X[ABC]\d{4})=PULSE\((\d+)\)$/)) && m[1] === ouverture && Number(m[2]) > 50) {
      note('ERREUR', `${id} : ${l} depasse le PULSE APERIO maximal (50)`);
    }
    if (l === `${ouverture}=1` || l === `${refus}=1`) note('ERREUR', `${id} : ${l} interdit sur une serrure APERIO`);
  });

  const ouvreParAperio = (ev, quoi) => {
    const lignes = instructionsEvenement(liste, ev);
    if (!lignes) { note('ERREUR', `${id} : ${quoi} sans ${ev}`); return; }
    if (!lignes.some(l => l.startsWith('APERIO_OPEN('))) note('ERREUR', `${id} : ${quoi} sans APERIO_OPEN`);
  };
  const actif = p.commandPolarity === 'inverted' || (options && options.commandPolarity === 'inverted') ? 0 : 1;
  if (p.cmdHyperActif !== false) ouvreParAperio(`EV(${d.cmdHyper}==${actif})`, 'commande hyperviseur');
  if (Number(p.bp) === 1) ouvreParAperio(`EV(${d.bp}==1)`, 'bouton poussoir');
  if (p.mode === 'visiteur') ouvreParAperio(`EV(${d.lecteur}==VISIT_AUTORISE)`, 'visiteur autorise');
  if (p.effractionActive !== false && !liste.includes(`SI(${ouverture}==0)`)) {
    note('ERREUR', `${id} : effraction APERIO sans SI(${ouverture}==0)`);
  }
}

// Lecteur biometrique (LBio) : l'ouverture n'a lieu que si BIO_STATUS == 00 ;
// sous INTERDIT, signalisation selon BIO_STATUS 01, 02 et 00.
function controlerBiometrie(p, d, id, liste, note) {
  // Porte a lecteur de sortie seul : la tete de la porte porte ce lecteur.
  [[p.lecteurEntree || p.lecteurSortie, d.lecteur], [p.lecteurSortie, d.lecteurSortie]].forEach(([type, lecteur]) => {
    if (!lecteur) return;
    const statut = `BIO_STATUS_${lecteur.slice(1)}`;
    if (String(type || '').trim().toUpperCase() !== 'LBIO') {
      if (liste.some(l => l.includes(`${statut}==`))) note('ERREUR', `${id} : ${statut} sur un lecteur non biometrique ${lecteur}`);
      return;
    }
    const autorise = instructionsEvenement(liste, `EV(${lecteur}==AUTORISE)`);
    if (!autorise) { note('ERREUR', `${id} : lecteur biometrique ${lecteur} sans EV(${lecteur}==AUTORISE)`); return; }
    if (autorise[0] !== `SI(${statut}==00)`) note('ERREUR', `${id} : ${lecteur} AUTORISE sans SI(${statut}==00) en tete`);
    const interdit = instructionsEvenement(liste, `EV(${lecteur}==INTERDIT)`) || [];
    ['01', '02', '00'].forEach(v => {
      if (!interdit.includes(`SI(${statut}==${v})`)) note('ERREUR', `${id} : ${lecteur} INTERDIT sans SI(${statut}==${v})`);
    });
  });
}

// Porte « commande seule » sur un relais de MLR8 (portail, barriere) : le relais
// X{bus}{adresse}0{n} et le registre M{24 + porte} (25..48, hors plage des tetes
// 1..24), rien d'autre. Microcode : EV(Mxx==actif) puis le PULSE du relais ;
// serveur -> UTL : .cmd seulement ; UTL -> serveur : aucune propriete.
const CHAMPS_VIDES_COMMANDE_SEULE = ['lecteur', 'ledVert', 'ledRouge', 'buzzer', 'capteur', 'bp', 'dm', 'ap',
  'timer', 'regEffrac', 'regPotl', 'pescort', 'lecteurSortie', 'ledVertSortie', 'ledRougeSortie', 'buzzerSortie'];

function controlerCommandeSeule(p, d, id, bloc, contexte, note) {
  const { utl, srv, options } = contexte;
  const relais = Number(d.relais);
  if (!(relais >= 1 && relais <= 8)) note('ERREUR', `${id} : relais MLR8 ${d.relais} hors 1..8`);
  const lock = `X${d.bus}${d.carte}0${relais}`;
  if (d.lock !== lock) note('ERREUR', `${id} : relais ${d.lock} au lieu de ${lock}`);
  if (d.cmdHyper !== `M${24 + d.porteNum}`) note('ERREUR', `${id} : cmdHyper=${d.cmdHyper} au lieu de M${24 + d.porteNum}`);
  const m = String(d.cmdHyper || '').match(/^M(\d+)$/);
  if (!m || Number(m[1]) < 25 || Number(m[1]) > 48) note('ERREUR', `${id} : commande ${d.cmdHyper} hors M25..M48`);
  CHAMPS_VIDES_COMMANDE_SEULE.forEach(champ => {
    if (d[champ]) note('ERREUR', `${id} : commande seule avec ${champ}=${d[champ]}`);
  });
  if (Number(d.lecteurNum) !== 0) note('ERREUR', `${id} : commande seule avec lecteurNum=${d.lecteurNum}`);
  if (d.bpActif || d.dmActif || d.apActif) note('ERREUR', `${id} : commande seule avec BP / DM / AP actif`);

  const liste = bloc ? instructionsBloc(bloc) : [];
  const actif = options && options.commandPolarity === 'inverted' ? 0 : 1;
  const pulse = p.dureePulse || (options && options.pulse) || 50;
  if (p.cmdHyperActif !== false) {
    const attendu = [`EV(${d.cmdHyper}==${actif})`, `${d.lock}=PULSE(${pulse})`];
    if (!bloc) note('ERREUR', `${id} : bloc absent du microcode`);
    else if (liste.join(' | ') !== attendu.join(' | ')) note('ERREUR', `${id} : bloc commande seule « ${liste.join(' | ')} » au lieu de « ${attendu.join(' | ')} »`);
    if (proprieteDe(srv, id, 'cmd') !== d.cmdHyper) note('ERREUR', `${id} : .cmd incoherent`);
  } else {
    if (liste.length) note('ERREUR', `${id} : commande hyperviseur desactivee mais bloc « ${liste.join(' | ')} »`);
    if (proprieteDe(srv, id, 'cmd') !== null) note('ERREUR', `${id} : .cmd present alors que la commande est desactivee`);
  }
  // Aucun retour d'etat : ni .locked, ni .forced, ni .potl, ni .dm, ni .ap.
  utl.split('\n').filter(l => l.startsWith(`${id}.`)).forEach(l => note('ERREUR', `${id} : propriete UTL -> serveur inattendue ${l.trim()}`));
}

// Valeur d'une propriete « id.cle=valeur », ou null si absente.
function proprieteDe(texte, id, cle) {
  const debut = `${id}.${cle}=`;
  const ligne = texte.split('\n').find(x => x.startsWith(debut));
  return ligne ? ligne.slice(debut.length).trim() : null;
}

// Porte sans lecteur (ni entree ni sortie) : ni tete, ni LED, ni buzzer.
function estPorteSansLecteur(p) {
  return !String(p.lecteurEntree || '').trim() && !String(p.lecteurSortie || '').trim();
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
  const propriete = proprieteDe;

  // Toute porte active rattachee a un MLR8 (8 relais au plus) est une porte
  // « commande seule » : elle doit etre raccordee et generee comme telle.
  (tillys.synopticModules || []).filter(m => m.type === 'MLR8').forEach(m => {
    (m.doorNums || []).slice(0, 8).forEach(num => {
      const p = tillys.portes[num - 1];
      const d = tableau.find(l => l.porteNum === num);
      if (p && p.active && d && !(d.raccorde && d.commandeSeule)) {
        note('ERREUR', `${d.triNum} : porte du ${m.name} non generee en commande seule`);
      }
    });
  });

  tableau.filter(d => d.active && d.raccorde).forEach(d => {
    const p = tillys.portes[d.porteNum - 1];
    const id = d.triNum;
    const bloc = blocs.find(b => b.startsWith(`${id} `)) || '';

    if (d.commandeSeule) {
      controlerCommandeSeule(p, d, id, bloc, { utl, srv, options }, note);
      [d.lock, d.cmdHyper].filter(Boolean).forEach(r => prendre(r, id));
      return;
    }

    if (!bloc) { note('ERREUR', `${id} : bloc absent du microcode`); return; }
    const regs = new Set(bloc.match(/\b(?:X[ABC]\d{4}|D[ABC]\d{4}|L[ABC]\d+|TN\d+|[MRV]\d+)\b/g) || []);
    const timerPotl = p.timerActif !== false && p.potlActif !== false;
    // Numero de la tete de la porte, qu'elle ait un lecteur ou non.
    const tete = (TIL.BUS_OFFSETS[d.bus] || 0) + Number(d.adresseModule) + Number(d.rang);
    const sansLecteur = estPorteSansLecteur(p) && !estPorteAperio(p);

    // Porte sans lecteur : ni tete, ni LED, ni buzzer (relais, capteur et
    // registres de la porte inchanges).
    if (sansLecteur) {
      ['lecteur', 'ledVert', 'ledRouge', 'buzzer', 'lecteurSortie', 'ledVertSortie', 'ledRougeSortie', 'buzzerSortie'].forEach(champ => {
        if (d[champ]) note('ERREUR', `${id} : porte sans lecteur avec ${champ}=${d[champ]}`);
      });
    }

    // Registres du microcode = registres du tableau d'adresses.
    const attendus = [d.lock, d.ledVert, d.ledRouge, d.lecteur];
    if (p.cmdHyperActif !== false) attendus.push(d.cmdHyper);
    if (timerPotl || p.effractionActive !== false) attendus.push(d.capteur);
    if (timerPotl) attendus.push(d.timer, d.regPotl, d.buzzer);
    if (p.effractionActive !== false) attendus.push(d.regEffrac);
    if (Number(p.bp) === 1) attendus.push(d.bp);
    if (d.lecteurSortie) attendus.push(d.lecteurSortie, d.ledVertSortie, d.ledRougeSortie);
    attendus.filter(Boolean).forEach(r => { if (!regs.has(r)) note('ERREUR', `${id} : ${r} du tableau absent du microcode`); });
    // Le buzzer de sortie sert au lecteur biometrique de sortie (BIO_STATUS 02).
    const permis = new Set([...attendus, d.buzzer, d.capteur, d.buzzerSortie].filter(Boolean));
    regs.forEach(r => { if (!permis.has(r)) note('ERREUR', `${id} : ${r} utilise mais absent du tableau`); });
    if (p.cmdHyperActif === false && regs.has(d.cmdHyper)) note('ERREUR', `${id} : commande hyperviseur desactivee mais ${d.cmdHyper} present`);
    if (!timerPotl && regs.has(d.timer)) note('ERREUR', `${id} : Timer / POTL desactive mais ${d.timer} present`);
    if (p.effractionActive === false && regs.has(d.regEffrac)) note('ERREUR', `${id} : effraction desactivee mais ${d.regEffrac} present`);

    // Registres virtuels = numero de la tete de lecture (meme sans lecteur).
    [['cmdHyper', 'M'], ['timer', 'TN'], ['regEffrac', 'R'], ['regPotl', 'V']].forEach(([cle, prefixe]) => {
      if (d[cle] !== `${prefixe}${tete}`) note('ERREUR', `${id} : ${cle}=${d[cle]} au lieu de ${prefixe}${tete}`);
    });

    // Proprietes echangees avec le serveur.
    if (p.cmdHyperActif !== false && propriete(srv, id, 'cmd') !== d.cmdHyper) note('ERREUR', `${id} : .cmd incoherent`);
    if (propriete(utl, id, 'locked') !== d.capteur) note('ERREUR', `${id} : .locked incoherent`);
    if (p.effractionActive !== false && propriete(utl, id, 'forced') !== d.regEffrac) note('ERREUR', `${id} : .forced incoherent`);
    if (timerPotl && propriete(utl, id, 'potl') !== d.regPotl) note('ERREUR', `${id} : .potl incoherent`);
    if ((Number(p.dm) === 1) !== (propriete(utl, id, 'dm') === d.dm)) note('ERREUR', `${id} : .dm incoherent`);
    if ((Number(p.barreAntiPanique) === 1) !== (propriete(utl, id, 'ap') === d.ap)) note('ERREUR', `${id} : .ap incoherent`);

    // Lecteur clavier : modele TIL LC (PCLVx=3,4,10 et evenements CR_*).
    [[p.lecteurEntree || p.lecteurSortie, d.lecteur, tete], [p.lecteurSortie, d.lecteurSortie, tete + 1]].forEach(([type, lecteur, num]) => {
      if (String(type || '').toUpperCase() !== 'LCODE' || !lecteur) return;
      ['AUTORISE', 'CR_OK', 'CR_KO', 'CR_TIMEOUT', 'INTERDIT'].forEach(ev => {
        if (!bloc.includes(`EV(${lecteur}==${ev})`)) note('ECART', `${id} : lecteur clavier ${lecteur} sans EV(${lecteur}==${ev})`);
      });
      if (!new RegExp(`^PCLV${num}=3,4,10`, 'm').test(code)) note('ECART', `${id} : lecteur clavier ${lecteur} sans PCLV${num}=3,4,10`);
    });
    // Mode visiteur : escorte sur la tete de la porte, jamais sans lecteur.
    const escorte = new RegExp(`^PESCORT${tete}=`, 'm').test(code);
    if (p.mode === 'visiteur' && d.lecteur && !escorte) note('ERREUR', `${id} : visiteur sans PESCORT${tete}`);
    if (sansLecteur && escorte) note('ERREUR', `${id} : PESCORT${tete} sur une porte sans lecteur`);
    if (sansLecteur && /VISIT_AUTORISE|ATT_ESCORTE|ESCORTE_KO/.test(bloc)) note('ERREUR', `${id} : evenements visiteur sur une porte sans lecteur`);

    const liste = instructionsBloc(bloc);
    if (estPorteAperio(p)) controlerPorteAperio(p, d, id, liste, regs, options, note);
    else controlerBiometrie(p, d, id, liste, note);

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
// Options :
//  - biometrie : garde les lecteurs LBio tires au sort (sinon LB, meme tirage) et
//    autorise un lecteur de sortie LBio ;
//  - aperio : ajoute des portes APERIO (serrure + lecteur, ou lecteur seul) et
//    fait varier la duree d'ouverture (plafond PULSE 50 des serrures APERIO) ;
//  - mlr8 : ajoute des portes « commande seule » sur les relais d'un MLR8 par bus
//    (relais demande parfois invalide ou deja pris) et retire les lecteurs de
//    quelques portes de MLP2 (porte sans lecteur, ou lecteur de sortie seul).
//    Ces tirages viennent apres tous les autres.
// Sans option, la suite des tirages est celle d'origine (S4 inchange).
function projetAleatoire(TIL, graine, { aperio = false, biometrie = false, mlr8 = false } = {}) {
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
        const porte = t.portes[num - 1];
        Object.assign(porte, {
          active: r() < 0.9, batiment: choix(['A', 'B']), etage: choix(['N0', 'N1']), numeroPorte: String(100 + num),
          designation: `Porte ${num}`, lecteurEntree: choix(['LB', 'LB', 'LCode', 'LBio']), lecteurSortie: deux ? choix(biometrie ? ['LB', 'LCode', 'LBio'] : ['LB', 'LCode']) : '',
          bp: r() < 0.5 ? 1 : 0, dm: r() < 0.5 ? 1 : 0, barreAntiPanique: r() < 0.2 ? 1 : 0, mode: r() < 0.2 ? 'visiteur' : 'standard',
          cmdHyperActif: r() > 0.1, timerActif: r() > 0.15, potlActif: r() > 0.15, effractionActive: r() > 0.15, mlp2ModuleId: module.id,
        });
        if (!biometrie && porte.lecteurEntree === 'LBio') porte.lecteurEntree = 'LB';
        if (aperio) {
          const u = r();
          if (u < 0.15) Object.assign(porte, { verrouillage: 'APERIO', lecteurEntree: 'APERIO', lecteurSortie: '', typeSerrure: 'libre' });
          else if (u < 0.22) Object.assign(porte, { lecteurEntree: 'APERIO', lecteurSortie: '' });
          porte.dureePulse = choix([50, 50, 30, 100]);
        }
        module.doorNums.push(num);
        tetes -= deux ? 2 : 1;
        num += 1;
      }
    }
    if (r() < 0.5) { const a = TIL.allocateAddress(t, bus, 'MLIO'); if (a) t.synopticModules.push({ id: `IO${bus}`, type: 'MLIO', bus, address: a, name: `MLIO ${bus}${a}`, doorNums: [] }); }
    if (r() < 0.5) { const a = TIL.allocateAddress(t, bus, 'MLR8'); if (a) t.synopticModules.push({ id: `R8${bus}`, type: 'MLR8', bus, address: a, name: `MLR8 ${bus}${a}`, doorNums: [] }); }
  });
  if (num <= 24 && r() < 0.3) Object.assign(t.portes[num - 1], { active: true, numeroPorte: String(100 + num), designation: 'Orpheline', lecteurEntree: 'LB' });
  if (mlr8) ajouterTiragesMlr8(TIL, t, r, choix);
  return t;
}

// Tirages de l'option mlr8, apres ceux du projet de base.
function ajouterTiragesMlr8(TIL, t, r, choix) {
  // Portes de MLP2 sans lecteur, ou avec un lecteur de sortie seul.
  t.synopticModules.filter(m => m.type === 'MLP2').forEach(module => {
    module.doorNums.forEach(num => {
      const porte = t.portes[num - 1];
      const u = r();
      if (estPorteAperio(porte)) return;
      if (u < 0.15) Object.assign(porte, { lecteurEntree: '', numeroEntree: '', lecteurSortie: '', numeroSortie: '' });
      else if (u < 0.22 && !porte.lecteurSortie) Object.assign(porte, { lecteurEntree: '', numeroEntree: '', lecteurSortie: 'LB' });
    });
  });

  // Portes libres (inactives et hors module) pour les commandes seules.
  const prises = new Set(t.synopticModules.flatMap(m => m.doorNums));
  const libres = t.portes.map((p, i) => i + 1).filter(num => !t.portes[num - 1].active && !prises.has(num));
  ['A', 'B', 'C'].forEach(bus => {
    let module = t.synopticModules.find(m => m.type === 'MLR8' && m.bus === bus);
    if (!module) {
      const address = TIL.allocateAddress(t, bus, 'MLR8');
      if (!address) return;
      module = { id: `R8${bus}`, type: 'MLR8', bus, address, name: `MLR8 ${bus}${address}`, doorNums: [] };
      t.synopticModules.push(module);
    }
    const nombre = 1 + Math.floor(r() * 3);
    for (let k = 0; k < nombre && libres.length && module.doorNums.length < 8; k += 1) {
      const num = libres.shift();
      Object.assign(t.portes[num - 1], {
        active: r() < 0.9, batiment: choix(['A', 'B']), etage: choix(['N0', 'N1']), numeroPorte: String(100 + num),
        designation: `Commande ${num}`, verrouillage: 'CMD', lecteurEntree: '', numeroEntree: '', lecteurSortie: '',
        // Equipements saisis a tort sur un portail : ignores par la commande seule.
        bp: r() < 0.5 ? 1 : 0, dm: r() < 0.5 ? 1 : 0, barreAntiPanique: r() < 0.2 ? 1 : 0, mode: r() < 0.2 ? 'visiteur' : 'standard',
        cmdHyperActif: r() > 0.15, mlr8Relais: choix([0, 1, 3, 3, 5, 8, 9, undefined]), mlp2ModuleId: '',
      });
      module.doorNums.push(num);
    }
  });
}

module.exports = { registreValide, controlerSyntaxe, controlerTillys, projetAleatoire, estPorteAperio };
