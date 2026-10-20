'use strict';

// Le code genere doit reproduire, instruction par instruction, les modeles TIL
// de « Documentation sur le projet » (24 portes sur 12 MLP2, BP, effraction +
// POTL, commande hyperviseur, DM et AP). Les seules differences admises sont des
// erreurs de copier-coller des modeles eux-memes, listees ici.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { chargerGenerator } = require('./helpers/charger-generator');
const { RACINE_PROJET } = require('./helpers/racine');

const TIL = chargerGenerator();
const DOC = path.join(RACINE_PROJET, 'Documentation sur le projet');
const OPTIONS = { pulse: 50, potl: 300, escort: 10, milestone: false, commandPolarity: 'normal' };

function projet(lecteur, visiteur) {
  const t = TIL.creerTillys(0, 'Modele');
  t.synopticModules = [];
  let num = 1;
  ['A', 'B', 'C'].forEach(bus => [1, 3, 5, 7].forEach(address => {
    const id = `${bus}${address}`;
    t.synopticModules.push({ id, type: 'MLP2', bus, address, name: `MLP2 ${id}`, doorNums: [num, num + 1], readerSlots: 2 });
    [num, num + 1].forEach(n => Object.assign(t.portes[n - 1], {
      active: true, batiment: 'BAT', etage: 'ETG', numeroPorte: `PORTE${n}`, designation: 'Description porte',
      lecteurEntree: lecteur, lecteurSortie: '', bp: 1, dm: 1, barreAntiPanique: 1,
      mode: visiteur ? 'visiteur' : 'standard', mlp2ModuleId: id,
    }));
    num += 2;
  }));
  return t;
}

// Instructions seules : sans commentaires ni espaces, libelle de porte generique.
const instructions = texte => texte.split(/\r?\n/)
  .map(l => l.replace(/;.*$/, '').replace(/\s+/g, ''))
  .filter(Boolean)
  .map(l => l.replace(/^"[^"]*"\./, 'PORTE.').replace(/^BAT_ETG_PORTE\d+\./, 'PORTE.'));

// Differences entre deux suites d'instructions (plus longue sous-suite commune).
function differences(modele, appli) {
  const n = modele.length;
  const m = appli.length;
  const L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      L[i][j] = modele[i] === appli[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    }
  }
  const diffs = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && modele[i] === appli[j]) { i += 1; j += 1; } else if (j < m && (i === n || L[i][j + 1] >= L[i + 1][j])) {
      diffs.push(`+ ${appli[j]}`); j += 1;
    } else {
      diffs.push(`- ${modele[i]}`); i += 1;
    }
  }
  return diffs.sort();
}

const lire = fichier => instructions(fs.readFileSync(path.join(DOC, fichier), 'utf8'));
// Erreurs des modeles TIL : porte 17 (bus C) qui teste la commande du bus B, et
// LED rouge (voie 07) eteinte a la place de la verte (06) sur CR_TIMEOUT des portes 6.
const ERREUR_PORTE_17 = ['+ SI(XC0101==0)', '- SI(XB0101==0)'];
const ERREUR_CLAVIER = ['+ XA0506=0', '+ XB0506=0', '+ XC0506=0', '- XA0507=0', '- XB0507=0', '- XC0507=0'];

[
  ['MODEL Microcode (LB _ EFFRAC+POTL).txt', 'LB', false, ERREUR_PORTE_17],
  ['MODEL Microcode (LB _ EFFRAC+POTL _ VISITEUR).txt', 'LB', true, ERREUR_PORTE_17],
  ['MODEL Microcode (LC _ EFFRAC+POTL).txt', 'LCode', false, [...ERREUR_PORTE_17, ...ERREUR_CLAVIER]],
  ['MODEL Microcode (LC _ EFFRAC+POTL _ VISITEUR).txt', 'LCode', true, [...ERREUR_PORTE_17, ...ERREUR_CLAVIER]],
].forEach(([fichier, lecteur, visiteur, admises], index) => {
  test(`T${index + 1} microcode identique au modele TIL ${fichier}`, () => {
    const appli = instructions(TIL.genererMicrocodeTillys(projet(lecteur, visiteur), OPTIONS));
    assert.deepEqual(differences(lire(fichier), appli), [...admises].sort());
  });
});

test('T5 proprietes SERVEUR vers UTL identiques au modele TIL', () => {
  const appli = instructions(TIL.genererServeurVersUTL(projet('LB', false), OPTIONS));
  assert.deepEqual(differences(lire('MODEL Propriétées envoyées SERVEUR vers UTL.txt'), appli), []);
});

test('T6 proprietes UTL vers SERVEUR identiques au modele TIL (hors erreurs des portes 17 et 18 du modele)', () => {
  const appli = instructions(TIL.genererUTLVersServeur(projet('LB', false), OPTIONS));
  // Le modele repete R16 / V16 et DB0106 pour les portes 17 et 18.
  assert.deepEqual(differences(lire('MODEL Propriétées envoyées UTL vers SERVEUR (Porte complete).txt'), appli), [
    '+ PORTE.forced=R17', '+ PORTE.forced=R18', '+ PORTE.locked=DC0106', '+ PORTE.potl=V17', '+ PORTE.potl=V18',
    '- PORTE.forced=R16', '- PORTE.forced=R16', '- PORTE.locked=DB0106', '- PORTE.potl=V16', '- PORTE.potl=V16',
  ].sort());
});
