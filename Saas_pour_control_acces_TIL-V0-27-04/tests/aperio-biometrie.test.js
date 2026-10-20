'use strict';

// Serrures APERIO et lecteurs biometriques (LBio) dans app/generator.js.
// Plan « APERIO + biometrie » : A1 a A15, B1 a B5 ; revue APERIO : A16 a A22.
//
// Regles retenues (MS_Cube_Microcode_et_Programmation.pdf, exemples 3.1 / 3.2) :
//  - une porte est APERIO si verrouillage === 'APERIO' ou lecteurEntree === 'APERIO' ;
//  - la serrure APERIO est la tete de lecture de la porte : X{bus}{lecteurLocal}03
//    (ouverture + LED verte) et ...04 (refus + LED rouge), pas de relais ni de buzzer ;
//  - BP et hyperviseur ouvrent par APERIO_OPEN(numero de lecteur, secondes) ;
//  - un lecteur LBio teste BIO_STATUS_{bus}{lecteurLocal} sous AUTORISE / INTERDIT.
const test = require('node:test');
const assert = require('node:assert/strict');
const { chargerGenerator } = require('./helpers/charger-generator');
const fx = require('./helpers/fixtures');

const TIL = chargerGenerator();
const OPTIONS = { pulse: 50, potl: 300, escort: 10, milestone: false, commandPolarity: 'normal' };
const SEPARATEUR = `;${'/'.repeat(64)}`;

// Instruction normalisee : commentaire retire, tous les espaces retires
// (APERIO_OPEN( 5 , 5 ) et APERIO_OPEN(5,5) sont la meme instruction).
function normaliser(ligne) {
  const sansCommentaire = ligne.includes(';') ? ligne.slice(0, ligne.indexOf(';')) : ligne;
  return sansCommentaire.replace(/\s+/g, '');
}

function instructions(lignes) {
  return lignes.map(normaliser).filter(Boolean);
}

// Instructions du bloc d'une porte : du titre « ;A_N0_x » au separateur suivant.
function blocPorte(microcode, triNum) {
  const lignes = microcode.split(/\r?\n/);
  const titre = new RegExp(`^;${triNum}(\\s|$)`);
  const debut = lignes.findIndex((ligne, i) => i > 0 && lignes[i - 1] === SEPARATEUR && titre.test(ligne));
  assert.ok(debut > 0, `bloc ${triNum} introuvable dans le microcode`);
  const fin = lignes.findIndex((ligne, i) => i > debut + 1 && ligne === SEPARATEUR);
  return instructions(lignes.slice(debut + 2, fin === -1 ? lignes.length : fin));
}

// Instructions d'un evenement : de EV(...) (exclu) au prochain EV( (exclu).
function evenement(liste, ev) {
  const debut = liste.indexOf(ev);
  assert.ok(debut >= 0, `${ev} absent du bloc :\n${liste.join(' | ')}`);
  const suite = liste.slice(debut + 1);
  const fin = suite.findIndex(l => l.startsWith('EV('));
  return fin === -1 ? suite : suite.slice(0, fin);
}

// Instructions d'un SI(...) jusqu'a son FINSI (imbrications comprises).
function blocSi(liste, si) {
  const debut = liste.indexOf(si);
  assert.ok(debut >= 0, `${si} absent :\n${liste.join(' | ')}`);
  let niveau = 0;
  for (let i = debut; i < liste.length; i += 1) {
    if (liste[i].startsWith('SI(')) niveau += 1;
    if (liste[i] === 'FINSI') niveau -= 1;
    if (niveau === 0) return liste.slice(debut + 1, i);
  }
  assert.fail(`${si} sans FINSI :\n${liste.join(' | ')}`);
  return [];
}

function contientSequence(liste, sequence) {
  for (let i = 0; i + sequence.length <= liste.length; i += 1) {
    if (sequence.every((valeur, j) => liste[i + j] === valeur)) return true;
  }
  return false;
}

function assertSequence(liste, sequence, message) {
  assert.ok(contientSequence(liste, sequence),
    `${message}\nattendu (sequence contigue) : ${sequence.join(' | ')}\nobtenu : ${liste.join(' | ')}`);
}

function microcode(tillys) {
  return TIL.genererMicrocodeTillys(tillys, OPTIONS);
}

const registresInternes = addr => [addr.cmdHyper, addr.timer, addr.regEffrac, addr.regPotl];
const aperioOpen = liste => liste.filter(l => l.startsWith('APERIO_OPEN('));

// ── APERIO : adressage ─────────────────────────────────────────────────

test('A1 porte 3 APERIO au rang 1 du MLP2 A1 : serrure sur la tete LA2 (XA0203 / XA0204), sans relais ni buzzer', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureAperio(TIL), 3);
  assert.equal(addr.aperio, true, 'addr.aperio attendu a true pour une porte APERIO');
  assert.equal(addr.lock, '', 'porte APERIO : pas de relais');
  assert.equal(addr.ledVert, 'XA0203', 'ouverture + LED verte sur la tete 2 (voie 03)');
  assert.equal(addr.ledRouge, 'XA0204', 'refus + LED rouge sur la tete 2 (voie 04)');
  assert.equal(addr.buzzer, '', 'porte APERIO : pas de buzzer');
  assert.equal(addr.lecteur, 'LA2');
  assert.equal(addr.lecteurNum, 2);
  assert.equal(addr.capteur, 'DA0106', 'contact de porte reste cable sur le MLP2');
  assert.equal(addr.bp, 'DA0105', 'BP reste cable sur le MLP2');
  assert.deepEqual(registresInternes(addr), ['M2', 'TN2', 'R2', 'V2']);
});

test('A2 exemple doc 3.1 : porte 6 APERIO sur MLP2 A5 (LA5) => XA0503 / XA0504', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureAperio(TIL), 6);
  assert.equal(addr.lecteur, 'LA5');
  assert.equal(addr.ledVert, 'XA0503');
  assert.equal(addr.ledRouge, 'XA0504');
  assert.equal(addr.lock, '', 'porte APERIO : pas de relais XA0501');
});

test('A3 exemple doc 3.2 : porte 5 APERIO sur MLP2 B1 (tete 9) => XB0103 / XB0104', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureAperioBusB(TIL), 5);
  assert.equal(addr.aperio, true, 'addr.aperio attendu a true');
  assert.equal(addr.lecteur, 'LB1');
  assert.equal(addr.lecteurNum, 9);
  assert.equal(addr.ledVert, 'XB0103');
  assert.equal(addr.ledRouge, 'XB0104');
  assert.equal(addr.lock, '');
});

test('A4 lecteur APERIO seul (verrouillage VENTOUSE) : la porte est APERIO', () => {
  const t = fx.fixtureBase(TIL);
  t.portes[0].lecteurEntree = 'APERIO';
  assert.equal(t.portes[0].verrouillage, 'VENTOUSE', 'precondition : porte 1 en ventouse');
  const addr = TIL.getPorteAddresses(t, 1);
  assert.equal(addr.aperio, true, 'lecteurEntree APERIO suffit a faire une porte APERIO');
  assert.equal(addr.lock, '', 'porte APERIO : pas de relais');
  assert.equal(addr.ledVert, 'XA0103');
  assert.equal(addr.ledRouge, 'XA0104');
});

test('A5 (non-regression) porte 1 ventouse a cote d\'une porte APERIO : adresses et bloc inchanges', () => {
  const t = fx.fixtureAperio(TIL);
  const addr = TIL.getPorteAddresses(t, 1);
  assert.ok(!addr.aperio, 'porte 1 ventouse : pas APERIO');
  assert.deepEqual([addr.lock, addr.ledVert, addr.ledRouge, addr.buzzer], ['XA0101', 'XA0103', 'XA0104', 'XA0105']);
  assert.deepEqual(blocPorte(microcode(t), 'A_N0_1'), [
    'EV(M1==1)', 'XA0103=PULSE(50)', 'XA0101=PULSE(50)',
    'EV(DA0102==0)', 'TN1=300', 'SI(XA0101==0)', 'R1=1', 'FINSI',
    'EV(TN1)', 'XA0105=1', 'V1=1',
    'EV(DA0102==1)', 'TN1=0', 'R1=0', 'V1=0', 'XA0105=0',
    'EV(LA1==AUTORISE)', 'XA0103=PULSE(50)', 'XA0101=PULSE(50)',
    'EV(LA1==INTERDIT)', 'XA0104=PULSE(30)',
    'EV(DA0101==1)', 'XA0103=PULSE(50)', 'XA0101=PULSE(50)',
  ]);
});

// ── APERIO : microcode ─────────────────────────────────────────────────

test('A6 bloc A_N0_6 : badge autorise / interdit sur les registres de la tete, aucune voie relais ni buzzer', () => {
  const code = microcode(fx.fixtureAperio(TIL));
  const bloc = blocPorte(code, 'A_N0_6');
  assertSequence(bloc, ['EV(LA5==AUTORISE)', 'XA0503=PULSE(50)'], 'badge autorise : ouverture APERIO par XA0503');
  assertSequence(bloc, ['EV(LA5==INTERDIT)', 'XA0504=PULSE(30)'], 'badge interdit : refus APERIO par XA0504');
  assert.ok(!bloc.some(l => l.includes('XA0501')), `XA0501 (relais) present dans le bloc APERIO : ${bloc.join(' | ')}`);
  assert.ok(!bloc.some(l => l.includes('XA0505')), `XA0505 (buzzer) present dans le bloc APERIO : ${bloc.join(' | ')}`);
  const troisChiffres = code.match(/\bX[ABC]\d{3}\b/g);
  assert.equal(troisChiffres, null, `registre a 3 chiffres dans le microcode : ${troisChiffres}`);
});

test('A7 commande hyperviseur : APERIO_OPEN(tete, secondes) et ouverture par la voie 03', () => {
  const bloc6 = blocPorte(microcode(fx.fixtureAperio(TIL)), 'A_N0_6');
  const hyper6 = evenement(bloc6, 'EV(M5==1)');
  assert.ok(hyper6.includes('APERIO_OPEN(5,5)'), `EV(M5==1) sans APERIO_OPEN(5,5) : ${hyper6.join(' | ')}`);
  assert.ok(hyper6.includes('XA0503=PULSE(50)'), `EV(M5==1) sans XA0503=PULSE(50) : ${hyper6.join(' | ')}`);

  const blocB = blocPorte(microcode(fx.fixtureAperioBusB(TIL)), 'B_N1_5');
  const hyperB = evenement(blocB, 'EV(M9==1)');
  assert.ok(hyperB.includes('APERIO_OPEN(9,5)'), `EV(M9==1) sans APERIO_OPEN(9,5) : ${hyperB.join(' | ')}`);
});

test('A8 bouton poussoir d\'une porte APERIO : APERIO_OPEN, aucun relais', () => {
  const bloc = blocPorte(microcode(fx.fixtureAperio(TIL)), 'A_N0_6');
  const bp = evenement(bloc, 'EV(DA0501==1)');
  assert.ok(bp.includes('APERIO_OPEN(5,5)'), `EV(DA0501==1) sans APERIO_OPEN(5,5) : ${bp.join(' | ')}`);
  assert.ok(!bp.some(l => /^XA050[12]=/.test(l)), `relais commande sur le BP APERIO : ${bp.join(' | ')}`);
});

test('A9 effraction APERIO : SI(XA0503==0) remplace le test du relais', () => {
  const bloc = blocPorte(microcode(fx.fixtureAperio(TIL)), 'A_N0_6');
  const ouverture = evenement(bloc, 'EV(DA0502==0)');
  assertSequence(ouverture, ['SI(XA0503==0)', 'R5=1', 'FINSI'], 'effraction testee sur la voie d\'ouverture APERIO');
  assert.ok(!ouverture.includes('SI(XA0501==0)'), `SI(XA0501==0) encore present : ${ouverture.join(' | ')}`);
});

test('A10 POTL APERIO : registre V garde, sans buzzer', () => {
  const bloc = blocPorte(microcode(fx.fixtureAperio(TIL)), 'A_N0_6');
  const potl = evenement(bloc, 'EV(TN5)');
  assert.ok(potl.includes('V5=1'), `EV(TN5) sans V5=1 : ${potl.join(' | ')}`);
  assert.ok(!potl.includes('XA0505=1'), `buzzer XA0505=1 sur une porte APERIO : ${potl.join(' | ')}`);
  const fermeture = evenement(bloc, 'EV(DA0502==1)');
  assert.ok(!fermeture.includes('XA0505=0'), `buzzer XA0505=0 sur une porte APERIO : ${fermeture.join(' | ')}`);
});

test('A11 duree d\'ouverture 10 s : PULSE plafonne a 50, duree reelle dans APERIO_OPEN', () => {
  const t = fx.fixtureAperio(TIL);
  t.portes[5].dureePulse = 100;
  const bloc = blocPorte(microcode(t), 'A_N0_6');
  const autorise = evenement(bloc, 'EV(LA5==AUTORISE)');
  assert.ok(autorise.includes('XA0503=PULSE(50)'), `badge autorise : XA0503=PULSE(50) attendu : ${autorise.join(' | ')}`);
  assert.ok(!bloc.includes('XA0503=PULSE(100)'), `XA0503=PULSE(100) depasse le plafond APERIO : ${bloc.join(' | ')}`);
  const hyper = evenement(bloc, 'EV(M5==1)');
  assert.ok(hyper.includes('APERIO_OPEN(5,10)'), `EV(M5==1) sans APERIO_OPEN(5,10) : ${hyper.join(' | ')}`);
});

test('A12 hyperviseur desactive + BP : un seul APERIO_OPEN, pas d\'EV(M5', () => {
  const t = fx.fixtureAperio(TIL);
  t.portes[5].cmdHyperActif = false;
  const bloc = blocPorte(microcode(t), 'A_N0_6');
  assert.ok(!bloc.some(l => l.startsWith('EV(M5')), `EV(M5 present alors que l'hyperviseur est desactive : ${bloc.join(' | ')}`);
  assert.deepEqual(aperioOpen(bloc), ['APERIO_OPEN(5,5)'], 'seul le BP ouvre par APERIO_OPEN');
});

test('A13 porte 3 APERIO en mode visiteur : VISIT_AUTORISE ouvre par APERIO_OPEN, jamais =1 sur 03 / 04', () => {
  const t = fx.fixtureAperio(TIL);
  t.portes[2].mode = 'visiteur';
  const bloc = blocPorte(microcode(t), 'A_N0_3');
  const visite = evenement(bloc, 'EV(LA2==VISIT_AUTORISE)');
  assert.ok(visite.includes('APERIO_OPEN(2,5)'), `VISIT_AUTORISE sans APERIO_OPEN(2,5) : ${visite.join(' | ')}`);
  assert.ok(visite.includes('XA0203=PULSE(50)'), `VISIT_AUTORISE sans XA0203=PULSE(50) : ${visite.join(' | ')}`);
  assert.ok(!bloc.includes('XA0203=1'), `XA0203=1 dans le bloc visiteur APERIO : ${bloc.join(' | ')}`);
  assert.ok(!bloc.includes('XA0204=1'), `XA0204=1 dans le bloc visiteur APERIO : ${bloc.join(' | ')}`);
});

test('A14 (non-regression) proprietes serveur de la porte APERIO A_N0_3 : contact, effraction, POTL, commande', () => {
  const t = fx.fixtureAperio(TIL);
  const utl = TIL.genererUTLVersServeur(t, OPTIONS).split(/\r?\n/).map(l => l.trim());
  const srv = TIL.genererServeurVersUTL(t, OPTIONS).split(/\r?\n/).map(l => l.trim());
  ['A_N0_3.locked=DA0106', 'A_N0_3.forced=R2', 'A_N0_3.potl=V2'].forEach(l => assert.ok(utl.includes(l), `${l} attendu`));
  assert.ok(srv.includes('A_N0_3.cmd=M2'), 'A_N0_3.cmd=M2 attendu');
});

test('A15 tableau d\'adresses de la porte APERIO 3 : drapeau aperio, pas de relais, LED sur la tete', () => {
  const ligne = TIL.genererTableauAdresses(fx.fixtureAperio(TIL)).find(l => l.porteNum === 3);
  assert.equal(ligne.aperio, true, 'ligne.aperio attendu a true');
  assert.equal(ligne.lock, '');
  assert.equal(ligne.ledVert, 'XA0203');
  assert.equal(ligne.ledRouge, 'XA0204');
});

// ── Biometrie ──────────────────────────────────────────────────────────

test('B1 lecteur LBio LB6 : badge autorise => ouverture seulement si BIO_STATUS_B6==00', () => {
  const bloc = blocPorte(microcode(fx.fixtureBio(TIL)), 'B_N0_8');
  assertSequence(bloc, ['EV(LB6==AUTORISE)', 'SI(BIO_STATUS_B6==00)', 'XB0506=PULSE(50)', 'XB0502=PULSE(50)', 'FINSI'],
    'AUTORISE : LED verte + ouverture sous condition biometrique');
});

test('B2 lecteur LBio LB6 : badge interdit => signalisation selon BIO_STATUS (01, 02, 00)', () => {
  const bloc = blocPorte(microcode(fx.fixtureBio(TIL)), 'B_N0_8');
  const interdit = evenement(bloc, 'EV(LB6==INTERDIT)');
  const trie = liste => [...liste].sort();
  assert.deepEqual(trie(blocSi(interdit, 'SI(BIO_STATUS_B6==01)')), trie(['XB0507=PULSE(30)', 'XB0506=PULSE(30)']),
    'BIO_STATUS 01 : LED rouge + LED verte');
  assert.deepEqual(trie(blocSi(interdit, 'SI(BIO_STATUS_B6==02)')), trie(['XB0507=PULSE(30)', 'XB0508=PULSE(30)']),
    'BIO_STATUS 02 : LED rouge + buzzer');
  assert.deepEqual(blocSi(interdit, 'SI(BIO_STATUS_B6==00)'), ['XB0507=PULSE(30)'], 'BIO_STATUS 00 : LED rouge');
  const si = interdit.filter(l => l.startsWith('SI(')).length;
  const finsi = interdit.filter(l => l === 'FINSI').length;
  assert.equal(si, finsi, `SI / FINSI desequilibres sous INTERDIT : ${interdit.join(' | ')}`);
});

test('B3 lecteur LBio : aucune ouverture avant le test BIO_STATUS', () => {
  const bloc = blocPorte(microcode(fx.fixtureBio(TIL)), 'B_N0_8');
  const autorise = evenement(bloc, 'EV(LB6==AUTORISE)');
  const condition = autorise.indexOf('SI(BIO_STATUS_B6==00)');
  assert.ok(condition >= 0, `SI(BIO_STATUS_B6==00) absent de EV(LB6==AUTORISE) : ${autorise.join(' | ')}`);
  assert.ok(!autorise.slice(0, condition).some(l => l.startsWith('XB0502')),
    `ouverture XB0502 avant le test biometrique : ${autorise.join(' | ')}`);
});

test('B4 lecteur de sortie LBio (porte 2, LA4) : ouverture sous BIO_STATUS_A4==00', () => {
  const bloc = blocPorte(microcode(fx.fixtureBio(TIL)), 'A_N0_2');
  const sortie = evenement(bloc, 'EV(LA4==AUTORISE)');
  assert.equal(sortie[0], 'SI(BIO_STATUS_A4==00)', `EV(LA4==AUTORISE) doit commencer par SI(BIO_STATUS_A4==00) : ${sortie.join(' | ')}`);
  const sousCondition = blocSi(sortie, 'SI(BIO_STATUS_A4==00)');
  assert.ok(sousCondition.includes('XA0306=PULSE(50)'), `LED verte sortie XA0306 attendue : ${sousCondition.join(' | ')}`);
  assert.ok(sousCondition.includes('XA0301=PULSE(50)'), `ouverture XA0301 attendue : ${sousCondition.join(' | ')}`);
});

test('B5 (non-regression) sans lecteur biometrique : aucun BIO_STATUS', () => {
  assert.ok(!microcode(fx.fixtureBase(TIL)).includes('BIO_STATUS'));
});

// ── Revue APERIO : lecteurs clavier / biometrique, commentaires, en-tete ──

// Lignes brutes (commentaires compris) dont la partie commentaire verifie le test.
function commentaires(code, critere) {
  return code.split(/\r?\n/)
    .filter(ligne => ligne.includes(';'))
    .map(ligne => ligne.slice(ligne.indexOf(';')))
    .filter(critere);
}

const avertissementEffraction = commentaire =>
  /APERIO/.test(commentaire) && /EFFRACTION/i.test(commentaire) && /\b5\s?s\b/i.test(commentaire);

test('A16 porte APERIO avec lecteur d\'entree LCode : aucun PCLV ni CR_OK pour sa tete, la porte reste APERIO', () => {
  const t = fx.fixtureAperio(TIL);
  t.portes[5].lecteurEntree = 'LCode';
  assert.equal(t.portes[5].verrouillage, 'APERIO', 'precondition : verrouillage APERIO');
  const addr = TIL.getPorteAddresses(t, 6);
  assert.equal(addr.aperio, true, 'precondition : la porte 6 reste APERIO');
  const code = microcode(t);
  const pclv = instructions(code.split(/\r?\n/)).filter(l => l.startsWith('PCLV5='));
  assert.deepEqual(pclv, [], 'serrure APERIO : pas de declaration clavier PCLV5 pour la tete LA5');
  const bloc = blocPorte(code, 'A_N0_6');
  assert.ok(!bloc.some(l => l.includes('CR_OK')), `CR_OK dans le bloc APERIO : ${bloc.join(' | ')}`);
  assertSequence(bloc, ['EV(LA5==AUTORISE)', 'XA0503=PULSE(50)'], 'badge autorise : ouverture APERIO par XA0503');
  assert.ok(aperioOpen(bloc).includes('APERIO_OPEN(5,5)'), `APERIO_OPEN(5,5) attendu : ${bloc.join(' | ')}`);
});

test('A17 porte APERIO avec lecteur d\'entree LBio : aucun BIO_STATUS pour sa tete, la porte reste APERIO', () => {
  const t = fx.fixtureAperio(TIL);
  t.portes[5].lecteurEntree = 'LBio';
  assert.equal(TIL.getPorteAddresses(t, 6).aperio, true, 'precondition : la porte 6 reste APERIO');
  const code = microcode(t);
  assert.ok(!code.includes('BIO_STATUS_A5'), 'serrure APERIO : pas de BIO_STATUS_A5');
  const bloc = blocPorte(code, 'A_N0_6');
  assertSequence(bloc, ['EV(LA5==AUTORISE)', 'XA0503=PULSE(50)'], 'badge autorise : ouverture APERIO par XA0503');
  assert.ok(aperioOpen(bloc).includes('APERIO_OPEN(5,5)'), `APERIO_OPEN(5,5) attendu : ${bloc.join(' | ')}`);
});

test('A18 duree d\'ouverture APERIO 10 s : commentaire d\'avertissement (repere 03 limite a 5 s, effraction possible)', () => {
  const t = fx.fixtureAperio(TIL);
  t.portes[5].dureePulse = 100;
  const lignes = commentaires(microcode(t), avertissementEffraction);
  assert.ok(lignes.length > 0,
    'commentaire attendu mentionnant APERIO, 5 s et EFFRACTION pour une ouverture APERIO de 10 s');
});

test('A19 (non-regression) duree d\'ouverture APERIO <= 5 s : aucun avertissement d\'effraction', () => {
  const t = fx.fixtureAperio(TIL);
  assert.deepEqual(commentaires(microcode(t), avertissementEffraction), [], 'duree par defaut 5 s : pas d\'avertissement');
  t.portes[5].dureePulse = 30;
  assert.deepEqual(commentaires(microcode(t), avertissementEffraction), [], 'duree 3 s : pas d\'avertissement');
});

test('A20 duree 2,5 s : APERIO_OPEN(5,3) commente avec la duree arrondie « 3s »', () => {
  const t = fx.fixtureAperio(TIL);
  t.portes[5].dureePulse = 25;
  const lignes = microcode(t).split(/\r?\n/).filter(l => normaliser(l) === 'APERIO_OPEN(5,3)');
  assert.ok(lignes.length > 0, 'precondition : APERIO_OPEN(5,3) present');
  lignes.forEach(ligne => {
    const commentaire = ligne.slice(ligne.indexOf(';'));
    assert.ok(ligne.includes(';'), `APERIO_OPEN(5,3) sans commentaire : ${ligne}`);
    assert.match(commentaire, /\b3\s?s\b/, `commentaire de APERIO_OPEN(5,3) : ${commentaire}`);
    assert.ok(!commentaire.includes('2.5'), `commentaire de APERIO_OPEN(5,3) avec la duree non arrondie : ${commentaire}`);
  });
});

const ligneFirmware = commentaire =>
  /APERIO_OPEN/.test(commentaire) && /TILLYS/i.test(commentaire) && /4\.2\.0/.test(commentaire);

function lignesEnTete(code) {
  const lignes = code.split(/\r?\n/);
  const init = lignes.findIndex(l => /Section d'initialisation/.test(l));
  assert.ok(init > 0, 'precondition : section d\'initialisation presente');
  return lignes.slice(0, init);
}

test('A21 en-tete : Tillys avec porte APERIO raccordee => APERIO_OPEN exige le firmware TILLYS 4.2.0 ou plus', () => {
  const entete = lignesEnTete(microcode(fx.fixtureAperio(TIL)));
  const lignes = commentaires(entete.join('\n'), ligneFirmware);
  assert.ok(lignes.length > 0,
    `en-tete sans mention du firmware TILLYS 4.2.0 pour APERIO_OPEN :\n${entete.join('\n')}`);
});

test('A22 (non-regression) en-tete sans porte APERIO raccordee : aucune mention du firmware 4.2.0', () => {
  assert.deepEqual(commentaires(microcode(fx.fixtureBase(TIL)), ligneFirmware), [], 'fixtureBase : pas de porte APERIO');
  const orpheline = fx.fixtureBase(TIL);
  Object.assign(orpheline.portes[9], { verrouillage: 'APERIO', lecteurEntree: 'APERIO' });
  assert.deepEqual(commentaires(microcode(orpheline), ligneFirmware), [], 'porte APERIO orpheline : non raccordee');
  const inactive = fx.fixtureAperioBusB(TIL);
  inactive.portes[4].active = false;
  assert.deepEqual(commentaires(microcode(inactive), ligneFirmware), [], 'porte APERIO inactive');
});
