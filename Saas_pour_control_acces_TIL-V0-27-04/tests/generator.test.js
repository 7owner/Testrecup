'use strict';

// Tests unitaires de app/generator.js (adressage, microcode, proprietes
// serveur, tableau d'adresses). Plan de tests « Logiciel TIL » : U1 a U16.
const test = require('node:test');
const assert = require('node:assert/strict');
const { chargerGenerator } = require('./helpers/charger-generator');
const fx = require('./helpers/fixtures');

const TIL = chargerGenerator();
const SEPARATEUR = `;${'/'.repeat(64)}`;

function registresInternes(addr) {
  return [addr.cmdHyper, addr.timer, addr.regEffrac, addr.regPotl];
}

// Ligne de microcode normalisee : commentaire retire, espaces reduits.
function normaliserLigne(ligne) {
  const sansCommentaire = ligne.includes(';') ? ligne.slice(0, ligne.indexOf(';')) : ligne;
  return sansCommentaire.trim().replace(/\s+/g, ' ');
}

// Bloc brut d'une porte : du titre « ;A_N0_x » au separateur de la porte suivante.
function blocPorte(microcode, triNum) {
  const lignes = microcode.split(/\r?\n/);
  const titre = new RegExp(`^;${triNum}(\\s|$)`);
  const debut = lignes.findIndex((ligne, i) => i > 0 && lignes[i - 1] === SEPARATEUR && titre.test(ligne));
  assert.ok(debut > 0, `bloc ${triNum} introuvable dans le microcode`);
  assert.equal(lignes[debut + 1], SEPARATEUR, `en-tete du bloc ${triNum} mal ferme`);
  const fin = lignes.findIndex((ligne, i) => i > debut + 1 && ligne === SEPARATEUR);
  return lignes.slice(debut + 2, fin === -1 ? lignes.length : fin);
}

function instructions(bloc) {
  return bloc.map(normaliserLigne).filter(Boolean);
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

function lignesTexte(texte) {
  return texte.split(/\r?\n/).map(l => l.trim());
}

// ── Adressage ──────────────────────────────────────────────────────────

test('U1 porte 3 au rang 1 du MLP2 A1 : LA2, lecteur 2, registres M2/TN2/R2/V2', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureBase(TIL), 3);
  assert.equal(addr.lecteur, 'LA2');
  assert.equal(addr.lecteurNum, 2);
  assert.deepEqual(registresInternes(addr), ['M2', 'TN2', 'R2', 'V2']);
});

test('U2 porte 2 sur le MLP2 A3 : LA3, registres M3/TN3/R3/V3', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureBase(TIL), 2);
  assert.equal(addr.lecteur, 'LA3');
  assert.deepEqual(registresInternes(addr), ['M3', 'TN3', 'R3', 'V3']);
});

test('U3 porte 5 sur MLP2 bus B adresse 1 : LB1, lecteur 9, registres M9/TN9/R9/V9', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureBusB(TIL), 5);
  assert.equal(addr.lecteur, 'LB1');
  assert.equal(addr.lecteurNum, 9);
  assert.deepEqual(registresInternes(addr), ['M9', 'TN9', 'R9', 'V9']);
});

test('U4 porte 4 sur MLP2 bus C adresse 1 : LC1, lecteur 17, registres M17/TN17/R17/V17', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureBusC(TIL), 4);
  assert.equal(addr.lecteur, 'LC1');
  assert.equal(addr.lecteurNum, 17);
  assert.deepEqual(registresInternes(addr), ['M17', 'TN17', 'R17', 'V17']);
});

test('U5 porte 6 sur MLP2 bus A adresse 5 : LA5, registres M5/TN5', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureLA5(TIL), 6);
  assert.equal(addr.lecteur, 'LA5');
  assert.equal(addr.cmdHyper, 'M5');
  assert.equal(addr.timer, 'TN5');
});

test('U6 (non-regression) porte 10 orpheline : registres au numero de porte, pas de relais', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureBase(TIL), 10);
  assert.equal(addr.orpheline, true);
  assert.deepEqual(registresInternes(addr), ['M10', 'TN10', 'R10', 'V10']);
  assert.equal(addr.lock, '');
});

test('U7 porte 10 orpheline : champs du lecteur de sortie vides', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureBase(TIL), 10);
  assert.equal(addr.lecteurSortie, '');
  assert.equal(addr.ledVertSortie, '');
  assert.equal(addr.ledRougeSortie, '');
  assert.equal(addr.buzzerSortie, '');
});

test('U8 porte 2 a deux lecteurs : sortie sur LA4 et voies 06-08, entree sur LA3', () => {
  const addr = TIL.getPorteAddresses(fx.fixtureBase(TIL), 2);
  assert.equal(addr.lecteurSortie, 'LA4');
  assert.equal(addr.ledVertSortie, 'XA0306');
  assert.equal(addr.ledRougeSortie, 'XA0307');
  assert.equal(addr.buzzerSortie, 'XA0308');
  assert.equal(addr.lecteur, 'LA3');
  assert.equal(addr.lock, 'XA0301');
  assert.equal(addr.ledVert, 'XA0303');
  assert.equal(addr.ledRouge, 'XA0304');
  assert.equal(addr.buzzer, 'XA0305');
  assert.equal(addr.capteur, 'DA0302');
});

test('U9 champs de sortie vides hors porte a deux lecteurs en rang 0', () => {
  const champs = addr => [addr.lecteurSortie, addr.ledVertSortie, addr.ledRougeSortie, addr.buzzerSortie];
  const vides = ['', '', '', ''];
  assert.deepEqual(champs(TIL.getPorteAddresses(fx.fixtureBase(TIL), 3)), vides, 'porte 3 (un seul lecteur)');
  assert.deepEqual(champs(TIL.getPorteAddresses(fx.fixtureSortieSansEntree(TIL), 1)), vides, 'porte avec lecteur de sortie sans lecteur d\'entree');
  assert.deepEqual(champs(TIL.getPorteAddresses(fx.fixtureDeuxLecteursRang1(TIL), 3)), vides, 'porte a deux lecteurs en rang 1');
});

// ── Microcode ──────────────────────────────────────────────────────────

test('U10 bloc microcode A_N0_1 : sequence exacte, sans commentaire de sortie libre', () => {
  const microcode = TIL.genererMicrocodeTillys(fx.fixtureBase(TIL), {});
  const bloc = blocPorte(microcode, 'A_N0_1');
  assert.deepEqual(instructions(bloc), [
    'EV(M1==1)', 'XA0103=PULSE(50)', 'XA0101=PULSE(50)',
    'EV(DA0102==0)', 'TN1=300', 'SI(XA0101==0)', 'R1=1', 'FINSI',
    'EV(TN1)', 'XA0105=1', 'V1=1',
    'EV(DA0102==1)', 'TN1=0', 'R1=0', 'V1=0', 'XA0105=0',
    'EV(LA1==AUTORISE)', 'XA0103=PULSE(50)', 'XA0101=PULSE(50)',
    'EV(LA1==INTERDIT)', 'XA0104=PULSE(30)',
    'EV(DA0101==1)', 'XA0103=PULSE(50)', 'XA0101=PULSE(50)',
  ]);
  const brut = bloc.join('\n');
  assert.ok(!brut.includes('BP sortie non utilise'), 'porte avec BP : pas de « BP sortie non utilise »');
  assert.ok(!brut.includes('Sortie Libre'), 'aucun commentaire « Sortie Libre » dans le bloc');
});

test('U11 bloc porte 2 : commande hyperviseur et lecteur de sortie LA4', () => {
  const microcode = TIL.genererMicrocodeTillys(fx.fixtureBase(TIL), {});
  const bloc = blocPorte(microcode, 'A_N0_2');
  const liste = instructions(bloc);
  assertSequence(liste, ['EV(M3==1)', 'XA0303=PULSE(50)', 'XA0306=PULSE(50)', 'XA0301=PULSE(50)'],
    'commande hyperviseur : LED verte entree, LED verte sortie, ouverture');
  assertSequence(liste, ['EV(LA4==AUTORISE)', 'XA0306=PULSE(50)', 'XA0301=PULSE(50)', 'EV(LA4==INTERDIT)', 'XA0307=PULSE(30)'],
    'evenements du lecteur de sortie LA4');
  assert.ok(!liste.includes('EV(DA0301==1)'), 'porte sans BP : pas d\'evenement BP');
  assert.ok(!bloc.join('\n').includes('BP sortie non utilise'), 'sortie par lecteur : pas de « BP sortie non utilise »');
});

test('U12 bloc porte 3 : BP non utilise signale une fois, registres M2/TN2/R2/V2', () => {
  const microcode = TIL.genererMicrocodeTillys(fx.fixtureBase(TIL), {});
  const bloc = blocPorte(microcode, 'A_N0_3');
  const occurrences = bloc.filter(ligne => ligne.trim() === ';BP sortie non utilise').length;
  assert.equal(occurrences, 1, '« ;BP sortie non utilise » attendu une fois');
  const liste = instructions(bloc);
  assert.ok(liste.includes('EV(M2==1)'), `EV(M2==1) absent : ${liste.join(' | ')}`);
  assert.ok(liste.includes('TN2=300') && liste.includes('EV(TN2)'), `timer TN2 absent : ${liste.join(' | ')}`);
  assert.ok(liste.includes('R2=1') && liste.includes('R2=0'), `registre R2 absent : ${liste.join(' | ')}`);
  assert.ok(liste.includes('V2=1') && liste.includes('V2=0'), `registre V2 absent : ${liste.join(' | ')}`);
});

test('U13 aucun commentaire « Sortie Libre » / « Passage Libre » quel que soit le type de serrure', () => {
  ['ventouse', 'aligator', 'libre'].forEach(typeSerrure => {
    const t = fx.fixtureBase(TIL);
    t.portes.forEach(porte => { porte.typeSerrure = typeSerrure; });
    const microcode = TIL.genererMicrocodeTillys(t, {});
    assert.ok(!/Sortie Libre/.test(microcode), `« Sortie Libre » present pour typeSerrure=${typeSerrure}`);
    assert.ok(!/Passage Libre/.test(microcode), `« Passage Libre » present pour typeSerrure=${typeSerrure}`);
  });
});

// ── Proprietes serveur ─────────────────────────────────────────────────

test('U14 proprietes UTL->serveur et serveur->UTL au numero de lecteur', () => {
  const t = fx.fixtureBase(TIL);
  const utlServeur = lignesTexte(TIL.genererUTLVersServeur(t, {}));
  assert.ok(utlServeur.includes('A_N0_1.locked=DA0102'), 'ligne exacte A_N0_1.locked=DA0102 attendue');
  assert.ok(!utlServeur.some(l => l.includes('locked=!')), 'aucune propriete locked inversee (locked=!)');
  assert.ok(utlServeur.includes('A_N0_1.forced=R1'), 'A_N0_1.forced=R1');
  assert.ok(utlServeur.includes('A_N0_1.potl=V1'), 'A_N0_1.potl=V1');
  assert.ok(utlServeur.includes('A_N0_1.dm=DA0103'), 'A_N0_1.dm=DA0103');
  assert.ok(utlServeur.includes('A_N0_3.forced=R2'), 'A_N0_3.forced=R2');

  const serveurUtl = lignesTexte(TIL.genererServeurVersUTL(t, {}));
  assert.ok(serveurUtl.includes('A_N0_2.cmd=M3'), 'A_N0_2.cmd=M3');
  assert.ok(serveurUtl.includes('A_N0_3.cmd=M2'), 'A_N0_3.cmd=M2');
});

// ── Tableau d'adresses ─────────────────────────────────────────────────

test('U15 tableau d\'adresses : BP / DM / AP actifs selon l\'equipement pose', () => {
  const lignes = TIL.genererTableauAdresses(fx.fixtureBase(TIL));
  const ligne = num => lignes.find(l => l.porteNum === num);
  const actifs = l => [l.bpActif, l.dmActif, l.apActif];

  assert.deepEqual(actifs(ligne(1)), [true, true, false], 'porte 1 : BP et DM poses, pas d\'AP');
  assert.deepEqual(actifs(ligne(2)), [false, false, false], 'porte 2 : aucun equipement');
  assert.equal(ligne(2).lecteurSortie, 'LA4', 'porte 2 : lecteur de sortie LA4');
  assert.deepEqual(actifs(ligne(4)), [false, false, false], 'porte 4 inactive par defaut');

  const avecAp = TIL.genererTableauAdresses(fx.fixtureAntiPanique(TIL)).find(l => l.porteNum === 3);
  assert.equal(avecAp.apActif, true, 'porte avec barre anti-panique : apActif');
});

test('U16 (non-regression) SET_RDR_COLOR une ligne par MLP2 actif, sur son adresse de base', () => {
  const microcode = TIL.genererMicrocodeTillys(fx.fixtureBase(TIL), {});
  const lignes = lignesTexte(microcode).filter(l => l.startsWith('SET_RDR_COLOR('));
  assert.deepEqual(lignes.map(l => l.match(/^SET_RDR_COLOR\((\d+),/)[1]), ['1', '3']);
});
