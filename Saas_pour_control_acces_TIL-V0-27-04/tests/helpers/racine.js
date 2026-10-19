'use strict';

// Racine de l'application testee. Par defaut le projet courant ; TIL_APP_ROOT
// permet de pointer une autre copie (ex. version packagee 2.0.5) pour verifier
// que les tests echouent bien sur l'ancien code.
const path = require('path');

const RACINE_PROJET = path.resolve(__dirname, '..', '..');

function getRacineApp() {
  const valeur = String(process.env.TIL_APP_ROOT || '').trim();
  if (!valeur) return RACINE_PROJET;
  return path.resolve(RACINE_PROJET, valeur);
}

module.exports = { RACINE_PROJET, getRacineApp };
