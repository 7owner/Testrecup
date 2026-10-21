'use strict';

// Coherence du microcode, des proprietes serveur et du tableau d'adresses avec
// les regles du systeme TIL (plages des registres, syntaxe, numerotation par
// tete de lecture, unicite du materiel, lecteur clavier selon le modele LC).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { chargerGenerator } = require('./helpers/charger-generator');
const fx = require('./helpers/fixtures');
const { registreValide, controlerSyntaxe, controlerTillys, projetAleatoire, estPorteAperio } = require('./helpers/coherence');

const TIL = chargerGenerator();
const OPTIONS = { pulse: 50, potl: 300, escort: 10, milestone: false, commandPolarity: 'normal' };
const problemes = resultat => resultat.constats.filter(c => c.gravite === 'ERREUR' || c.gravite === 'ECART').map(c => c.message);

test('S1 plages du systeme TIL : registres acceptes et refuses', () => {
  ['XA0101', 'DC1616', 'LA1', 'LC8', 'TN32', 'M128', 'R1', 'V24'].forEach(r => assert.ok(registreValide(r), r));
  ['XA0001', 'XA1701', 'DA0117', 'LA9', 'LA0', 'TN33', 'M129', 'V0', 'XA101'].forEach(r => assert.ok(!registreValide(r), r));
});

test('S2 fixtures (2 lecteurs, bus B et C, adresse 5, modules terrain) : microcode coherent avec le tableau et le systeme', () => {
  [fx.fixtureBase, fx.fixtureBusB, fx.fixtureBusC, fx.fixtureLA5, fx.fixtureAntiPanique, fx.fixtureModulesTerrain, fx.fixture24Portes]
    .forEach(fabrique => {
      const resultat = controlerTillys(TIL, fabrique(TIL), OPTIONS);
      assert.deepEqual(problemes(resultat), [], fabrique.name);
      assert.ok(resultat.portes > 0, `${fabrique.name} : aucune porte generee`);
    });
});

test('S3 lecteur clavier (LCode) : PCLV et evenements badge + code du modele TIL LC', () => {
  const t = fx.fixtureBase(TIL);
  t.portes[0].lecteurEntree = 'LCode';
  t.portes[1].lecteurSortie = 'LCode';
  const resultat = controlerTillys(TIL, t, OPTIONS);
  assert.deepEqual(problemes(resultat), []);
  const code = TIL.genererMicrocodeTillys(t, OPTIONS);
  assert.match(code, /^PCLV1=3,4,10/m, 'clavier en entree de la porte 1 (LA1)');
  assert.match(code, /^PCLV4=3,4,10/m, 'clavier en sortie de la porte 2 (LA4)');
  assert.doesNotMatch(code, /^PCLV3=/m, 'pas de PCLV sur le lecteur badge LA3');
  assert.match(code, /EV\(LA1==CR_OK\)\s*;[^\n]*\n\s*XA0104=0[^\n]*\n\s*XA0103=PULSE\(50\)[^\n]*\n\s*XA0101=PULSE\(50\)/, 'code autorise : ouverture');
  assert.match(code, /EV\(LA1==AUTORISE\)[^\n]*\n\s*XA0103=PULSE\(100\)[^\n]*\n\s*XA0104=PULSE\(100\)/, 'badge autorise : attente du code');
  assert.doesNotMatch(code.split('EV(LA1==AUTORISE)')[1].split('EV(LA1==CR_OK)')[0], /XA0101/, 'le badge seul n\'ouvre pas');
});

test('S4 300 projets aleatoires valides : aucune incoherence', () => {
  let portes = 0;
  const erreurs = [];
  for (let graine = 1; graine <= 300; graine += 1) {
    const resultat = controlerTillys(TIL, projetAleatoire(TIL, graine), OPTIONS);
    portes += resultat.portes;
    problemes(resultat).forEach(m => { if (erreurs.length < 10) erreurs.push(`graine ${graine} : ${m}`); });
  }
  assert.deepEqual(erreurs, []);
  assert.ok(portes > 1000, `trop peu de portes generees (${portes})`);
});

// ── APERIO et biometrie ────────────────────────────────────────────────

test('S5 syntaxe APERIO_OPEN / APERIO_CLOSE / BIO_STATUS : formes acceptees et refusees', () => {
  const constats = code => {
    const notes = [];
    controlerSyntaxe(code, (gravite, message) => notes.push(message));
    return notes;
  };
  // Un SI isole serait refuse pour SI / FINSI desequilibres : il est ferme ici.
  const si = condition => [`SI(${condition})`, 'FINSI'].join('\n');
  ['APERIO_OPEN(1,5)', 'APERIO_OPEN(24,3600)', 'APERIO_CLOSE(9)', 'APERIO_OPEN( 5 , 5 )',
    si('BIO_STATUS_B6==00'), si('BIO_STATUS_A1==01'), si('BIO_STATUS_C8==02')]
    .forEach(code => assert.deepEqual(constats(code), [], `accepte : ${code}`));
  ['APERIO_OPEN(25,5)', 'APERIO_OPEN(0,5)', 'APERIO_CLOSE(25)', si('BIO_STATUS_B9==00'), si('BIO_STATUS_B6==03'), 'XA053=PULSE(10)']
    .forEach(code => assert.ok(constats(code).length > 0, `refuse : ${code}`));
});

test('S6 fixtures APERIO (bus A, bus B) et biometrie : microcode coherent avec le tableau et le systeme', () => {
  [fx.fixtureAperio, fx.fixtureAperioBusB, fx.fixtureBio].forEach(fabrique => {
    const resultat = controlerTillys(TIL, fabrique(TIL), OPTIONS);
    assert.deepEqual(problemes(resultat), [], fabrique.name);
    assert.ok(resultat.portes > 0, `${fabrique.name} : aucune porte generee`);
  });
});

test('S7 300 projets aleatoires avec portes APERIO et lecteurs biometriques : aucune incoherence', () => {
  let portes = 0;
  let aperio = 0;
  let bio = 0;
  const erreurs = [];
  for (let graine = 1; graine <= 300; graine += 1) {
    const t = projetAleatoire(TIL, graine, { aperio: true, biometrie: true });
    t.portes.filter(p => p.active && p.mlp2ModuleId).forEach(p => {
      if (estPorteAperio(p)) aperio += 1;
      if (p.lecteurEntree === 'LBio' || p.lecteurSortie === 'LBio') bio += 1;
    });
    const resultat = controlerTillys(TIL, t, OPTIONS);
    portes += resultat.portes;
    problemes(resultat).forEach(m => { if (erreurs.length < 10) erreurs.push(`graine ${graine} : ${m}`); });
  }
  assert.ok(aperio > 100, `precondition : trop peu de portes APERIO tirees (${aperio})`);
  assert.ok(bio > 100, `precondition : trop peu de lecteurs biometriques tires (${bio})`);
  assert.deepEqual(erreurs, []);
  assert.ok(portes > 1000, `trop peu de portes generees (${portes})`);
});

// ── Logiciel TIL V2 : porte sans lecteur, commande seule sur relais MLR8 ──

test('S8 fixtures porte sans lecteur et commande seule MLR8 : microcode coherent avec le tableau et le systeme', () => {
  [fx.fixtureSansLecteur, fx.fixtureMlr8Commande].forEach(fabrique => {
    const resultat = controlerTillys(TIL, fabrique(TIL), OPTIONS);
    assert.deepEqual(problemes(resultat), [], fabrique.name);
  });
  const t = fx.fixtureMlr8Commande(TIL);
  const porte4 = TIL.genererTableauAdresses(t).find(l => l.porteNum === 4);
  assert.equal(porte4.commandeSeule, true, 'porte 4 : commande seule dans le tableau d\'adresses');
  assert.equal(controlerTillys(TIL, t, OPTIONS).portes, 4, 'portes generees : 1, 2, 3 (MLP2) et 4 (MLR8), pas la 10 orpheline');
  // Polarite inversee et commande coupee restent coherentes.
  assert.deepEqual(problemes(controlerTillys(TIL, t, { ...OPTIONS, commandPolarity: 'inverted' })), [], 'polarite inversee');
  t.portes[3].cmdHyperActif = false;
  assert.deepEqual(problemes(controlerTillys(TIL, t, OPTIONS)), [], 'commande hyperviseur coupee');
});

test('S9 300 projets aleatoires avec commandes seules MLR8 et portes sans lecteur : aucune incoherence', () => {
  let portes = 0;
  let commandes = 0;
  let sansLecteur = 0;
  const erreurs = [];
  for (let graine = 1; graine <= 300; graine += 1) {
    const t = projetAleatoire(TIL, graine, { mlr8: true });
    TIL.genererTableauAdresses(t).filter(d => d.active).forEach(d => {
      if (d.commandeSeule) commandes += 1;
      const p = t.portes[d.porteNum - 1];
      if (d.raccorde && !d.commandeSeule && !p.lecteurEntree && !p.lecteurSortie) sansLecteur += 1;
    });
    const resultat = controlerTillys(TIL, t, OPTIONS);
    portes += resultat.portes;
    problemes(resultat).forEach(m => { if (erreurs.length < 10) erreurs.push(`graine ${graine} : ${m}`); });
  }
  assert.deepEqual(erreurs, []);
  assert.ok(commandes > 300, `trop peu de portes commande seule generees (${commandes})`);
  assert.ok(sansLecteur > 100, `trop peu de portes sans lecteur raccordees (${sansLecteur})`);
  assert.ok(portes > 1000, `trop peu de portes generees (${portes})`);
});

test('S10 le controle detecte une commande seule mal generee (LED en trop, retour .locked)', () => {
  const t = fx.fixtureMlr8Commande(TIL);
  const fausse = (cle, transformer) => ({ ...TIL, [cle]: (tillys, options) => transformer(TIL[cle](tillys, options)) });
  // Microcode : une voie de plus apres l'ouverture du relais 3.
  const ledEnTrop = fausse('genererMicrocodeTillys', code => code.replace(/^(\s*XA0903=PULSE\(\d+\).*)$/m, '$1\n   XA0904=PULSE(30)'));
  assert.ok(problemes(controlerTillys(ledEnTrop, t, OPTIONS)).some(m => m.includes('A_N0_4') && m.includes('XA0904')),
    'une instruction en trop dans le bloc de la commande seule doit etre signalee');
  // UTL -> serveur : un retour d'etat sur une porte qui n'en a pas.
  const retour = fausse('genererUTLVersServeur', texte => `${texte}\nA_N0_4.locked=DA0902\n`);
  assert.ok(problemes(controlerTillys(retour, t, OPTIONS)).some(m => m.includes('A_N0_4') && m.includes('.locked')),
    'une propriete .locked sur une commande seule doit etre signalee');
});
