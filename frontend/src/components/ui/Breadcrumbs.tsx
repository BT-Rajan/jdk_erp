import { Fragment } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'

export interface BreadcrumbItem {
  label: string
  to?: string
}

export interface BreadcrumbsProps {
  items: BreadcrumbItem[]
}

/** Takes `items` as a prop -- the app computes the trail from its own
 * routing, this component has no router/path knowledge of its own
 * (unlike jdk_clean's version, which embedded a path->label registry
 * directly in the component). */
export function Breadcrumbs({ items }: BreadcrumbsProps) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex items-center gap-1 text-sm text-gold-100/60">
        {items.map((item, index) => {
          const isLast = index === items.length - 1
          return (
            <Fragment key={`${item.label}-${index}`}>
              {index > 0 && <ChevronRight size={14} aria-hidden="true" className="text-gold-100/30" />}
              <li>
                {item.to && !isLast ? (
                  <Link to={item.to} className="hover:text-gold-300">
                    {item.label}
                  </Link>
                ) : (
                  <span aria-current={isLast ? 'page' : undefined} className={isLast ? 'text-gold-100' : undefined}>
                    {item.label}
                  </span>
                )}
              </li>
            </Fragment>
          )
        })}
      </ol>
    </nav>
  )
}
