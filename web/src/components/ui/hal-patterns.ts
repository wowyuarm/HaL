import { cva, type VariantProps } from 'class-variance-authority'

export const HAL_READING_COLUMN_CLASS = 'mx-auto w-full max-w-[49rem]'

export const halPaperObjectVariants = cva('rounded-md border', {
  variants: {
    surface: {
      paper: 'border-subtle bg-hal-paper',
      panel: 'border-border bg-hal-panel',
      danger: 'border-danger bg-hal-danger-subtle',
    },
    density: {
      compact: 'px-2.5 py-1.5',
      comfortable: 'px-3 py-2.5',
      spacious: 'px-5 py-4',
      roomy: 'px-5 py-6',
    },
    seam: {
      none: '',
      human: 'border-l-2 border-l-human',
    },
  },
  defaultVariants: {
    surface: 'paper',
    density: 'compact',
    seam: 'none',
  },
})

export type HalPaperObjectVariants = VariantProps<typeof halPaperObjectVariants>
