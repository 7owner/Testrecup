'use strict';

// Modele Excel de l'auto-control : il est copie a chaque export. Il ne contient
// que la fiche, sans donnees ni couleurs d'un ancien chantier, sans macros.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { getRacineApp } = require('./helpers/racine');

const XLSX = require(path.join(getRacineApp(), 'app', 'vendor', 'xlsx.full.min.js'));
const MODELE = path.join(getRacineApp(), 'Documentation sur le projet', 'Modele fiche auto control_fauche.xlsx');
const DONNEES_CHANTIER = /SARTOR|\bP17\b|P17[-_]|ARCHIVE|LUDO/i;
// Couleurs des statuts dans l'application (onglet Auto Control).
const COULEURS = { NC: 'FFC7CE', C: 'DAF2D0', NV: 'E4DFEC', EX: 'D9D9D9' };

function lireModele() {
  assert.ok(fs.existsSync(MODELE), `modele absent : ${MODELE}`);
  return XLSX.read(fs.readFileSync(MODELE), { bookVBA: true, bookSST: true, cellStyles: true, cellFormula: true });
}

test('M1 modele auto-control : une seule feuille, sans macros, formules ni donnees de chantier', () => {
  const wb = lireModele();
  assert.deepEqual(wb.SheetNames, ['Fiche auto control']);
  assert.ok(!wb.vbaraw, 'le modele ne doit plus contenir de macros');
  const ws = wb.Sheets['Fiche auto control'];
  const cellules = Object.keys(ws).filter(ref => ref[0] !== '!');
  const chantier = cellules.filter(ref => typeof ws[ref].v === 'string' && DONNEES_CHANTIER.test(ws[ref].v));
  assert.deepEqual(chantier.slice(0, 10), [], 'cellules avec des donnees de chantier');
  const chaines = (wb.Strings || []).map(s => s && s.t).filter(t => t && DONNEES_CHANTIER.test(t));
  assert.deepEqual(chaines.slice(0, 10), [], 'chaines partagees avec des donnees de chantier');
  assert.deepEqual(cellules.filter(ref => ws[ref].f), [], 'aucune formule (elles lisaient des feuilles supprimees)');
});

test('M2 modele auto-control : zone des portes sans couleur, legende aux couleurs de l\'application', () => {
  const ws = lireModele().Sheets['Fiche auto control'];
  const colorees = Object.keys(ws)
    .filter(ref => ref[0] !== '!')
    .filter(ref => {
      const ligne = Number(ref.replace(/[A-Z]+/, ''));
      return ligne >= 15 && ligne <= 270 && ws[ref].s && ws[ref].s.patternType === 'solid';
    });
  assert.deepEqual(colorees.slice(0, 10), [], 'couleurs d\'exemple encore presentes dans la zone des portes');
  const fond = ref => (ws[ref] && ws[ref].s && ws[ref].s.fgColor && ws[ref].s.fgColor.rgb) || '';
  assert.equal(fond('AJ4'), COULEURS.NC, 'legende NC');
  assert.equal(fond('AJ5'), COULEURS.C, 'legende C');
  assert.equal(fond('AJ6'), COULEURS.NV, 'legende NV');
  assert.equal(fond('AJ7'), COULEURS.EX, 'legende non pris en consideration (exempte)');
  assert.equal(ws.A13 && ws.A13.v, 'PORTE');
  assert.equal((ws.A15 || {}).v, undefined, 'aucune porte d\'exemple');
});
