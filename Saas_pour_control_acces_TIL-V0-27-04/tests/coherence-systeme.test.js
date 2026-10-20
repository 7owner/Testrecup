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
