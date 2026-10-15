// ==========================================
// レポートの「ひとこと」（その週の作業時間に合わせて、くすっと笑える言葉を添える）
// 0分の週ほど責めずに、次の「5分だけ」へ誘う。文はここだけで決めているので、自由に書き換えてよい
// ==========================================
const CHEER_MESSAGES = {
  // 2週続けて0分
  zeroAgain: [
    "2週連続で0分。アプリがちょっと寂しがっています。……そのままで良いのか？ だまされたと思って、5分だけ。",
    "0分の記録が2週続いています（悪い意味で連続記録更新中）。この記録、5分で止められます。",
    "タイマーが2週間ほど暇そうにしています。そのままで良いのか？ 5分だけ相手をしてあげてください。",
  ],
  // 今週は0分（前の週は記録あり）
  zero: [
    "今週は0分。充電期間ということにしておきましょう。……そろそろ満タンでは？",
    "今週は0分でした。「Just do it.」のはずが、今週は「Just rest.」だったようです。",
    "今週の記録は0分。先週のあなたが、ちょっと首をかしげています。まずは5分だけ。",
  ],
  // 週の目標を達成
  goalReached: [
    "今週の目標、達成です！ 有言実行とはこのことですね。",
    "目標クリア！ 来週の自分へのハードルが、ちょっとだけ上がりました。",
  ],
  // 7日すべてに記録あり
  everyDay: [
    "7日すべてに記録あり。もはや習慣と呼んでいいレベルです。",
    "7日連続で記録しました。カレンダーに花丸をあげたい気分です。",
  ],
  // 前の週の2倍以上
  doubled: [
    "前の週の2倍以上！ 何があったんですか（いい意味で）。",
    "前の週の2倍以上。今週のあなた、ちょっと別人です。",
  ],
  // 1〜29分
  small: [
    "ゼロじゃない。それがすべての始まりです。来週はあと5分だけ上乗せを。",
    "小さくても一歩は一歩。来週はこの記録を、こっそり超えてみましょう。",
  ],
  // 30分〜2時間
  warm: [
    "エンジンがかかってきました。このまま冷やさないように。",
    "いい感じに温まってきました。来週もこの火を消さないように。",
  ],
  // 2〜5時間
  solid: [
    "なかなかの積み上げです。来週の自分にちょっと自慢できます。",
    "しっかり積み上がっています。このペース、なかなか真似できません。",
  ],
  // 5時間以上
  intense: [
    "今週はかなり本気でしたね。休むのも作戦のうちです。",
    "今週のがんばりには、レポートを書いている側も驚いています。ほどよく休んでくださいね。",
  ],
};

// どのひとことにするか（上から順に、最初に当てはまったもの）。goalMinutes は週の目標（0 なら目標なし）
function cheerKind_(current, previous, goalMinutes) {
  if (current.totalMinutes === 0) {
    return previous.totalMinutes === 0 ? "zeroAgain" : "zero";
  }
  if (goalMinutes > 0 && current.totalMinutes >= goalMinutes) return "goalReached";
  if (current.days === 7) return "everyDay";
  if (previous.totalMinutes > 0 && current.totalMinutes >= previous.totalMinutes * 2) return "doubled";
  if (current.totalMinutes < 30) return "small";
  if (current.totalMinutes < 120) return "warm";
  if (current.totalMinutes < 300) return "solid";
  return "intense";
}

// 毎週同じ文にならないよう、週ごとに順番に変える（同じ週なら、テストメールを何度送っても同じ文）
function cheerMessage_(report) {
  const messages = CHEER_MESSAGES[cheerKind_(report.current, report.previous, report.goalMinutes)];
  const weekNumber = Math.floor(daysSinceEpoch_(report.week.start) / 7);
  return messages[weekNumber % messages.length];
}

// 1970/1/1 から何日目か（日付だけで数える。夏時間などで時刻がずれても日数が変わらないように）
function daysSinceEpoch_(date) {
  return Math.round(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86400000);
}
