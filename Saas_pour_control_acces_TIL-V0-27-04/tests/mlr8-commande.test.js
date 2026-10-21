'use strict';

// Logiciel TIL V2, app/generator.js :
//  - porte sans lecteur et porte a lecteur de sortie seul : N1 a N4 ;
//  - porte « commande seule » sur un relais de MLR8 (portail, barriere) : F1 a F13.
//
// Regles retenues pour la commande seule :
//  - la porte appartient a module.doorNums d'un MLR8 et porte.mlr8Relais (1-8)
//    choisit son relais ; relais absent, invalide ou deja pris => premier relais
//    libre dans l'ordre de doorNums ; plus de relais libre => pas de relais ;
//  - relais X{bus}{adresse}0{n}, commande hyperviseur M{24 + numero de porte}
//    (25..48, hors plage des tetes de lecture), rien d'autre ;
//  - microcode : EV(Mxx==1) (==0 en polarite inversee) puis X..0n=PULSE(pulse) ;
//  - serveur -> UTL : .cmd seulement ; UTL -> serveur : aucune propriete.
const test = require('node:test');
const assert = require('node:assert/strict');
const { chargerGenerator } = require('./helpers/charger-generator');
const fx = require('./helpers/fixtures');

const TIL = chargerGenerator();
const OPTIONS = { pulse: 50, potl: 300, escort: 10, milestone: false, commandPolarity: 'normal' };
const SEPARATEUR = `;${'/'.repeat(64)}`;
const MARQUE_ENTREE = ';////////// ENTREE //////////';
const MARQUE_SORTIE = ';////////// SORTIE //////////';

// Instruction normalisee : commentaire et espaces retires.
function normaliser(ligne) {
  const sansCommentaire = ligne.includes(';') ? ligne.slice(0, ligne.indexOf(';')) : ligne;
  return sansCommentaire.replace(/\s+/g, '');
}

// Lignes brutes du bloc d'une porte : du titre « ;A_N0_x » au separateur suivant.
function lignesBloc(microcode, triNum) {
  const lignes = microcode.split(/\r?\n/);
  const titre = new RegExp(`^;${triNum}(\\s|$)`);
  const debut = lignes.findIndex((ligne, i) => i > 0 && lignes[i - 1] === SEPARATEUR && titre.test(ligne));
  if (debut < 0) return null;
  const fin = lignes.findIndex((ligne, i) => i > debut + 1 && ligne === SEPARATEUR);
  return lignes.slice(debut + 2, fin === -1 ? lignes.length : fin);
}

function blocPorte(microcode, triNum) {
  const lignes = lignesBloc(microcode, triNum);
  assert.ok(lignes, `bloc ${triNum} introuvable dans le microcode`);
  return lignes.map(normaliser).filter(Boolean);
}

// Instructions d'un evenement : de EV(...) exclu au prochain EV( exclu.
function evenement(liste, ev) {
  const debut = liste.indexOf(ev);
  assert.ok(debut >= 0, `${ev} absent du bloc :\n${liste.join(' | ')}`);
  const suite = liste.slice(debut + 1);
  const fin = suite.findIndex(l => l.startsWith('EV('));
  return fin === -1 ? suite : suite.slice(0, fin);
}

function lignesTexte(texte) {
  return texte.split(/\r?\n/).map(l => l.trim());
}

const microcode = (tillys, options = OPTIONS) => TIL.genererMicrocodeTillys(tillys, options);
const ligneTableau = (tillys, num) => TIL.genererTableauAdresses(tillys).find(l => l.porteNum === num);

// MLR8 A9 portant les portes donnees (doorNums dans cet ordre), relais demandes.
function fixtureRelais(demandes) {
  const t = fx.fixtureMlr8Commande(TIL);
  const mr9 = t.synopticModules.find(m => m.id === 'MR9');
  mr9.doorNums = [];
  demandes.forEach(([num, relais]) => {
    Object.assign(t.portes[num - 1], {
      active: true, batiment: 'A', etage: 'N0', numeroPorte: String(num), designation: `Portail ${num}`,
      verrouillage: 'CMD', lecteurEntree: '', lecteurSortie: '', mlr8Relais: relais,
    });
    mr9.doorNums.push(num);
  });
  return t;
}

// ── Porte sans lecteur, porte a lecteur de sortie seul ────────────────

test('N1 porte 3 sans lecteur : ni tete, ni LED, ni buzzer ; relais et registres au numero de tete', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureSansLecteur(TIL), 3);
  assert.equal(addr.orpheline, false, 'precondition : porte 3 raccordee au MLP2 A1');
  assert.deepEqual([addr.lecteur, addr.ledVert, addr.ledRouge, addr.buzzer], ['', '', '', ''],
    'lecteur, LED verte, LED rouge et buzzer vides');
  assert.deepEqual([addr.cmdHyper, addr.timer, addr.regEffrac, addr.regPotl], ['M2', 'TN2', 'R2', 'V2'],
    'M / TN / R / V gardent le numero de la tete (rang 1 du MLP2 A1)');
  assert.equal(addr.lock, 'XA0102', 'relais de la porte inchange');
  assert.equal(addr.capteur, 'DA0106', 'etat porte inchange');
});

test('N2 microcode de la porte 3 sans lecteur : aucun EV(L, ouverture hyperviseur et BP sans LED', () => {
  const t = fx.fixtureSansLecteur(TIL);
  t.portes[2].bp = 1;
  const liste = blocPorte(microcode(t), 'A_N0_3');
  assert.ok(!liste.some(l => l.startsWith('EV(L')), `evenement lecteur sur une porte sans lecteur :\n${liste.join(' | ')}`);
  assert.deepEqual(evenement(liste, 'EV(M2==1)'), ['XA0102=PULSE(50)'], 'hyperviseur : ouverture seule, sans LED');
  assert.deepEqual(evenement(liste, 'EV(DA0105==1)'), ['XA0102=PULSE(50)'], 'BP : ouverture seule, sans LED');
  ['XA0106', 'XA0107', 'XA0108'].forEach(voie => {
    assert.ok(!liste.some(l => l.includes(voie)), `voie LED / buzzer ${voie} utilisee :\n${liste.join(' | ')}`);
  });
  assert.ok(liste.includes('EV(DA0106==0)') && liste.includes('R2=1'), 'effraction et POTL conserves sur le capteur');
});

test('N3 porte sans lecteur en mode visiteur : ni PESCORT ni evenements visiteur', () => {
  const t = fx.fixtureSansLecteur(TIL);
  t.portes[2].mode = 'visiteur';
  const code = microcode(t);
  assert.ok(!/^PESCORT2=/m.test(code), 'pas d\'escorte sur la tete 2 sans lecteur');
  const liste = blocPorte(code, 'A_N0_3');
  ['ATT_ESCORTE', 'VISIT_AUTORISE', 'ESCORTE_KO'].forEach(ev => {
    assert.ok(!liste.some(l => l.includes(ev)), `${ev} sur une porte sans lecteur :\n${liste.join(' | ')}`);
  });
  const couleurs = lignesTexte(code).filter(l => l.startsWith('SET_RDR_COLOR(')).map(l => l.match(/^SET_RDR_COLOR\((\d+),/)[1]);
  assert.deepEqual(couleurs, ['1', '3'], 'SET_RDR_COLOR inchange');
});

test('N4 porte 1 a lecteur de sortie seul : ses evenements lecteur passent sous « SORTIE »', () => {
  const lignes = lignesBloc(microcode(fx.fixtureSortieSansEntree(TIL)), 'A_N0_1');
  assert.ok(lignes, 'bloc A_N0_1 introuvable');
  const brut = lignes.map(l => l.trim());
  const sortie = brut.indexOf(MARQUE_SORTIE);
  assert.ok(sortie >= 0, `marque « ${MARQUE_SORTIE} » absente`);
  const autorise = brut.findIndex(l => normaliser(l) === 'EV(LA1==AUTORISE)');
  const interdit = brut.findIndex(l => normaliser(l) === 'EV(LA1==INTERDIT)');
  assert.ok(autorise >= 0 && interdit >= 0, 'precondition : evenements du lecteur LA1 generes');
  assert.ok(autorise > sortie, 'EV(LA1==AUTORISE) doit etre sous la marque SORTIE');
  assert.ok(interdit > sortie, 'EV(LA1==INTERDIT) doit etre sous la marque SORTIE');
  const entree = brut.indexOf(MARQUE_ENTREE);
  if (entree >= 0) {
    const section = brut.slice(entree + 1, sortie).map(normaliser).filter(Boolean);
    assert.deepEqual(section.filter(l => l.includes('LA1')), [], 'rien du lecteur LA1 dans la section ENTREE');
  }
});

// ── Commande seule sur relais MLR8 ───────────────────────────────────────

test('F1 getRelaisMlr8Porte : porte 4 sur le relais 3 du MLR8 A9, null hors MLR8', () => {
  assert.equal(typeof TIL.getRelaisMlr8Porte, 'function', 'TIL.getRelaisMlr8Porte doit etre exporte');
  const t = fx.fixtureMlr8Commande(TIL);
  const r = TIL.getRelaisMlr8Porte(t, 4);
  assert.ok(r, 'porte 4 : relais attendu');
  assert.equal(r.module && r.module.id, 'MR9');
  assert.equal(r.relais, 3);
  assert.equal(TIL.getRelaisMlr8Porte(t, 1), null, 'porte 1 sur un MLP2 : pas de relais MLR8');
  assert.equal(TIL.getRelaisMlr8Porte(t, 10), null, 'porte 10 orpheline : pas de relais MLR8');
});

test('F2 getRelaisMlr8Porte : relais explicite libre, sinon premier libre dans l\'ordre de doorNums, sinon null', () => {
  assert.equal(typeof TIL.getRelaisMlr8Porte, 'function', 'TIL.getRelaisMlr8Porte doit etre exporte');
  const relais = (t, num) => (TIL.getRelaisMlr8Porte(t, num) || {}).relais || null;
  // 4 demande 3 (libre), 5 demande 3 (pris), 6 sans demande, 7 demande 0, 8 demande 9.
  const t = fixtureRelais([[4, 3], [5, 3], [6, undefined], [7, 0], [8, 9]]);
  assert.deepEqual([4, 5, 6, 7, 8].map(n => relais(t, n)), [3, 1, 2, 4, 5]);
  // Huit relais pris : la neuvieme porte n'a pas de relais.
  const plein = fixtureRelais([[1, 1], [2, 2], [3, 3], [4, 4], [5, 5], [6, 6], [7, 7], [8, 8], [9, 0]]);
  assert.equal(relais(plein, 8), 8, 'precondition : huitieme relais attribue');
  assert.equal(TIL.getRelaisMlr8Porte(plein, 9), null, 'neuvieme porte : aucun relais libre');
});

test('F3 getPorteAddresses porte 4 : commande seule XA0903 / M28, tout le reste vide', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  Object.assign(t.portes[3], { bp: 1, dm: 1, barreAntiPanique: 1, mode: 'visiteur' });
  const addr = TIL.getPorteAddresses(t, 4);
  assert.equal(addr.orpheline, false, 'porte 4 raccordee au MLR8');
  assert.equal(addr.commandeSeule, true);
  assert.equal(addr.relais, 3);
  assert.equal(addr.bus, 'A');
  assert.equal(addr.carte, '09');
  assert.equal(addr.lock, 'XA0903');
  assert.equal(addr.cmdHyper, 'M28');
  ['lecteur', 'ledVert', 'ledRouge', 'buzzer', 'capteur', 'bp', 'dm', 'ap', 'timer', 'regEffrac', 'regPotl', 'pescort']
    .forEach(champ => assert.equal(addr[champ], '', `${champ} vide`));
  assert.equal(addr.lecteurNum, 0, 'aucune tete de lecture');
});

test('F4 commande hyperviseur M{24 + porte} (M25..M48), portes a tete inchangees', () => {
  const t = fixtureRelais([[12, 1], [24, 2], [9, 3]]);
  // Les portes de la fixture de reference restent sur leurs MLP2.
  assert.equal(TIL.getPorteAddresses(t, 12).cmdHyper, 'M36');
  assert.equal(TIL.getPorteAddresses(t, 12).lock, 'XA0901');
  assert.equal(TIL.getPorteAddresses(t, 24).cmdHyper, 'M48');
  assert.equal(TIL.getPorteAddresses(t, 9).cmdHyper, 'M33');
  assert.equal(TIL.getPorteAddresses(t, 1).cmdHyper, 'M1', 'porte 1 (MLP2 A1) inchangee');
  assert.equal(TIL.getPorteAddresses(t, 2).cmdHyper, 'M3', 'porte 2 (MLP2 A3) inchangee');
});

test('F5 bloc microcode de la porte 4 : EV(M28==1) puis XA0903=PULSE(50), rien d\'autre', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  Object.assign(t.portes[3], { bp: 1, dm: 1, barreAntiPanique: 1, mode: 'visiteur' });
  assert.deepEqual(blocPorte(microcode(t), 'A_N0_4'), ['EV(M28==1)', 'XA0903=PULSE(50)']);
});

test('F6 polarite inversee : EV(M28==0) ; commande hyperviseur coupee : ni M28 ni XA0903', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  assert.deepEqual(blocPorte(microcode(t, { ...OPTIONS, commandPolarity: 'inverted' }), 'A_N0_4'), ['EV(M28==0)', 'XA0903=PULSE(50)']);
  t.portes[3].cmdHyperActif = false;
  const code = microcode(t);
  assert.ok(!/\bM28\b/.test(code), 'M28 present alors que la commande est coupee');
  assert.ok(!/\bXA0903\b/.test(code), 'XA0903 present alors que la commande est coupee');
  assert.ok(code.includes('EV(M1==1)'), 'precondition : les autres portes restent generees');
});

test('F7 ordre : la commande seule suit les portes a tete de son bus, avant le bus suivant', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  Object.assign(t.portes[4], { active: true, designation: 'Porte bus B', batiment: 'B', etage: 'N1', numeroPorte: '5', mlp2ModuleId: 'MB1', lecteurEntree: 'LB' });
  t.synopticModules.push({ id: 'MB1', type: 'MLP2', bus: 'B', address: 1, name: 'MLP2 B1', readerSlots: 2, doorNums: [5] });
  const lignes = microcode(t).split(/\r?\n/);
  const titre = tri => lignes.findIndex((l, i) => i > 0 && lignes[i - 1] === SEPARATEUR && new RegExp(`^;${tri}(\\s|$)`).test(l));
  const evenementielle = lignes.findIndex(l => l.includes('Section evenementielle'));
  const busB = lignes.findIndex((l, i) => i > evenementielle && /^;-+BUS B-+$/.test(l));
  const positions = ['A_N0_1', 'A_N0_3', 'A_N0_2', 'A_N0_4'].map(titre);
  positions.forEach((pos, i) => assert.ok(pos > 0, `bloc ${['A_N0_1', 'A_N0_3', 'A_N0_2', 'A_N0_4'][i]} absent`));
  assert.ok(busB > 0, 'precondition : section BUS B presente');
  assert.ok(positions[3] > Math.max(...positions.slice(0, 3)), 'A_N0_4 apres les portes a tete du bus A');
  assert.ok(positions[3] < busB, 'A_N0_4 avant la section du bus B');
});

test('F8 initialisation : SET_RDR_COLOR inchange, ni PESCORT ni avertissement d\'orpheline pour la commande seule', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  t.portes[3].mode = 'visiteur';
  const code = microcode(t);
  const couleurs = lignesTexte(code).filter(l => l.startsWith('SET_RDR_COLOR(')).map(l => l.match(/^SET_RDR_COLOR\((\d+),/)[1]);
  assert.deepEqual(couleurs, ['1', '3']);
  assert.ok(!/^PESCORT(0|28)=/m.test(code), 'pas d\'escorte pour une commande seule');
  const avertissement = code.split('Section d\'initialisation')[0];
  assert.ok(!avertissement.includes('A_N0_4'), `la porte 4 est listee comme porte sans module :\n${avertissement}`);
});

test('F9 proprietes serveur -> UTL : A_N0_4.cmd=M28, prefixe MIL_DOOR_ en mode Milestone', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  assert.ok(lignesTexte(TIL.genererServeurVersUTL(t, OPTIONS)).includes('A_N0_4.cmd=M28'), 'A_N0_4.cmd=M28 attendu');
  assert.ok(lignesTexte(TIL.genererServeurVersUTL(t, { ...OPTIONS, milestone: true })).includes('MIL_DOOR_A_N0_4.cmd=M28'),
    'MIL_DOOR_A_N0_4.cmd=M28 attendu');
});

test('F10 proprietes UTL -> serveur : aucune ligne pour la commande seule', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  Object.assign(t.portes[3], { dm: 1, barreAntiPanique: 1 });
  assert.equal(TIL.getPorteAddresses(t, 4).commandeSeule, true, 'precondition : porte 4 generee en commande seule');
  [OPTIONS, { ...OPTIONS, milestone: true }].forEach(options => {
    const lignes = lignesTexte(TIL.genererUTLVersServeur(t, options));
    assert.ok(lignes.includes(`${options.milestone ? 'MIL_DOOR_' : ''}A_N0_1.locked=DA0102`), 'precondition : porte 1 remontee');
    assert.deepEqual(lignes.filter(l => /^(MIL_DOOR_)?A_N0_4\./.test(l)), [], 'aucune propriete pour A_N0_4');
  });
});

test('F11 tableau d\'adresses : porte 4 commande seule raccordee, BP / DM / AP inactifs', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  Object.assign(t.portes[3], { bp: 1, dm: 1, barreAntiPanique: 1 });
  const l = ligneTableau(t, 4);
  assert.equal(l.commandeSeule, true);
  assert.equal(l.raccorde, true);
  assert.equal(l.lock, 'XA0903');
  assert.equal(l.cmdHyper, 'M28');
  assert.deepEqual([l.bpActif, l.dmActif, l.apActif], [false, false, false]);
  assert.ok(!ligneTableau(t, 1).commandeSeule, 'porte 1 (MLP2) : pas de commande seule');
});

test('F12 tableau des modules : le relais R3 pris par la porte 4 n\'est plus une voie libre', () => {
  const voies = TIL.genererTableauModules(fx.fixtureMlr8Commande(TIL)).filter(v => v.moduleId === 'MR9').map(v => v.label);
  assert.deepEqual(voies, ['R1', 'R2', 'R4', 'R5', 'R6', 'R7', 'R8']);
  const mlio = TIL.genererTableauModules(fx.fixtureMlr8Commande(TIL)).filter(v => v.moduleId === 'MI10');
  assert.equal(mlio.length, 16, 'MLIO A10 inchange');
});

test('F13 (non-regression) relais saisi sans appartenance au MLR8 : la porte reste orpheline', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  t.synopticModules.find(m => m.id === 'MR9').doorNums = [];
  const addr = TIL.getPorteAddresses(t, 4);
  assert.equal(addr.orpheline, true);
  assert.equal(addr.lock, '');
  assert.ok(!addr.commandeSeule, 'pas de commande seule hors doorNums');
});
