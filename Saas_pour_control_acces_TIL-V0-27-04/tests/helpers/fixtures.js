'use strict';

// Donnees synthetiques uniquement : jamais til_projet.json ni fichier client.
// Chaque fabrique recoit l'API TIL (vm ou page) et renvoie un Tillys complet.

function configurerPorte(t, num, valeurs) {
  Object.assign(t.portes[num - 1], { active: true }, valeurs);
  return t.portes[num - 1];
}

function moduleMLP2(id, bus, address, doorNums) {
  return { id, type: 'MLP2', bus, address, name: `MLP2 ${bus}${address}`, readerSlots: 2, doorNums };
}

// Fixture de reference :
//  - porte 1 (A_N0_1) sur MLP2 A1 rang 0, BP + DM, boite de jonction, COFFRET 1
//  - porte 3 (A_N0_3) sur MLP2 A1 rang 1, gache, ni BP ni DM
//  - porte 2 (A_N0_2) sur MLP2 A3, KEL, lecteur en entree ET en sortie
//  - porte 10 active sans module (orpheline)
function fixtureBase(TIL) {
  const t = TIL.creerTillys(0, 'Tillys 1');
  configurerPorte(t, 1, {
    designation: 'Local Velos', batiment: 'A', etage: 'N0', numeroPorte: '1',
    verrouillage: 'VENTOUSE', lecteurEntree: 'LB', numeroEntree: '001',
    bp: 1, dm: 1, boiteJonctionPlafond: true, coffret: 'COFFRET 1',
    mlp2ModuleId: 'MA1', mlp2Attribue: 'MLP2 A1',
  });
  configurerPorte(t, 2, {
    designation: 'Hall', batiment: 'A', etage: 'N0', numeroPorte: '2',
    verrouillage: 'KEL', lecteurEntree: 'LB', lecteurSortie: 'LB',
    mlp2ModuleId: 'MA3', mlp2Attribue: 'MLP2 A3',
  });
  configurerPorte(t, 3, {
    designation: 'Bureau', batiment: 'A', etage: 'N0', numeroPorte: '3',
    verrouillage: 'GACHE', lecteurEntree: 'LB',
    mlp2ModuleId: 'MA1', mlp2Attribue: 'MLP2 A1',
  });
  configurerPorte(t, 10, {
    designation: 'Local orphelin', batiment: 'A', etage: 'N1', numeroPorte: '10',
    verrouillage: 'VENTOUSE', lecteurEntree: 'LB',
  });
  t.synopticModules = [
    moduleMLP2('MA1', 'A', 1, [1, 3]),
    moduleMLP2('MA3', 'A', 3, [2]),
  ];
  return t;
}

// Porte 5 sur un MLP2 du bus B a l'adresse 1.
function fixtureBusB(TIL) {
  const t = fixtureBase(TIL);
  configurerPorte(t, 5, { designation: 'Porte bus B', batiment: 'B', etage: 'N1', numeroPorte: '5', mlp2ModuleId: 'MB1' });
  t.synopticModules.push(moduleMLP2('MB1', 'B', 1, [5]));
  return t;
}

// Porte 4 sur un MLP2 du bus C a l'adresse 1.
function fixtureBusC(TIL) {
  const t = fixtureBase(TIL);
  configurerPorte(t, 4, { designation: 'Porte bus C', batiment: 'C', etage: 'N2', numeroPorte: '4', mlp2ModuleId: 'MC1' });
  t.synopticModules.push(moduleMLP2('MC1', 'C', 1, [4]));
  return t;
}

// Porte 6 sur un MLP2 du bus A a l'adresse 5.
function fixtureLA5(TIL) {
  const t = fixtureBase(TIL);
  configurerPorte(t, 6, { designation: 'Porte LA5', batiment: 'A', etage: 'N0', numeroPorte: '6', mlp2ModuleId: 'MA5' });
  t.synopticModules.push(moduleMLP2('MA5', 'A', 5, [6]));
  return t;
}

// Porte 1 (rang 0) avec un lecteur de sortie mais sans lecteur d'entree.
function fixtureSortieSansEntree(TIL) {
  const t = fixtureBase(TIL);
  Object.assign(t.portes[0], { lecteurEntree: '', numeroEntree: '', lecteurSortie: 'LB' });
  return t;
}

// Porte 3 (rang 1 du MLP2 A1) avec lecteur d'entree et de sortie.
function fixtureDeuxLecteursRang1(TIL) {
  const t = fixtureBase(TIL);
  Object.assign(t.portes[2], { lecteurSortie: 'LB' });
  return t;
}

// Porte 3 equipee d'une barre anti-panique.
function fixtureAntiPanique(TIL) {
  const t = fixtureBase(TIL);
  t.portes[2].barreAntiPanique = 1;
  return t;
}

// Fixture de reference + MLR8 en A09 et MLIO en A10.
function fixtureModulesTerrain(TIL) {
  const t = fixtureBase(TIL);
  t.synopticModules.push(
    { id: 'MR9', type: 'MLR8', bus: 'A', address: 9, name: 'MLR8 A9', doorNums: [] },
    { id: 'MI10', type: 'MLIO', bus: 'A', address: 10, name: 'MLIO A10', doorNums: [] },
  );
  return t;
}

// 24 portes actives a designations longues (mise en page du PDF de reperage).
function fixture24Portes(TIL) {
  const t = fixtureBase(TIL);
  for (let num = 1; num <= 24; num += 1) {
    const porte = t.portes[num - 1];
    porte.active = true;
    if (!porte.batiment) Object.assign(porte, { batiment: 'B', etage: 'N2', numeroPorte: String(num) });
    porte.designation = `Local technique courant faible et stockage materiel securite incendie numero ${num}`;
    porte.typePorte = 'PORTE CLASSIQUE';
    porte.menuiserie = 'BOIS';
  }
  return t;
}

// Aucune porte active.
function fixtureSansPorteActive(TIL) {
  return TIL.creerTillys(0, 'Tillys 1');
}

module.exports = {
  fixtureBase,
  fixtureBusB,
  fixtureBusC,
  fixtureLA5,
  fixtureSortieSansEntree,
  fixtureDeuxLecteursRang1,
  fixtureAntiPanique,
  fixtureModulesTerrain,
  fixture24Portes,
  fixtureSansPorteActive,
};
