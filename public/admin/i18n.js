export const messages={
  ru:{overview:'Обзор',pos:'POS',floor:'Зал',kitchen:'Кухня',reservations:'Бронь / Waitlist',staff:'Персонал',finance:'Финансы',inventory:'Склад',purchasing:'Закупки',crm:'CRM гостей',delivery:'Доставка',tasks:'Задачи',reports:'Отчёты',settings:'Настройки'},
  tj:{overview:'Шарҳ',pos:'POS',floor:'Толор',kitchen:'Ошхона',reservations:'Брон / Навбат',staff:'Кормандон',finance:'Молия',inventory:'Анбор',purchasing:'Харид',crm:'CRM меҳмонон',delivery:'Расонидан',tasks:'Вазифаҳо',reports:'Ҳисобот',settings:'Танзимот'}
};
export function tr(key,lang='ru'){return messages[lang]?.[key]??messages.ru[key]??key;}
